import sqlite3

import pytest

from src.psb.parser import Product
from src.storage import Storage
from src.snapshot_merge import merge_bank


@pytest.fixture
def databases(tmp_path):
    paths = [tmp_path / "main.db", tmp_path / "isolated.db"]
    for path in paths:
        store = Storage(path)
        first = store.start_run("ЛНР")
        store.save_products(first, [Product(bank="Сбер", title="Старый вклад", collected_at="2026-11-10T10:00:00")])
        store.finish_run(first, psb=0, sber=1, promos=0)
        store.conn.execute("UPDATE runs SET finished_at='2026-11-10T12:00:00'")
        store.conn.commit()
        second = store.start_run("ЛНР")
        store.save_products(second, [Product(bank="Сбер", title="Новый вклад", collected_at="2026-11-13T10:00:00",
                                            terms={"evidence": "original"}),
                                     Product(bank="ВТБ", title=path.stem, collected_at="2026-11-13T11:00:00")])
        store.save_coverage(second, "Сбер", {"Вклады": "https://sber.example/deposit"})
        store.finish_run(second, psb=0, sber=1, promos=0, note="partial crawl")
        store.close()
    return paths


def test_merge_preserves_latest_rivals_dates_and_evidence(databases):
    dest, source = databases
    new = merge_bank(dest, source, bank="Сбер", source_run=2, expected_main_run=2, after_source_run=1)
    store = Storage(dest)
    assert store.last_successful_run_id() == new
    assert store.products_of_run(new, "ВТБ")[0]["title"] == "main"
    for field in ("collected_at", "terms_json", "region_method", "fingerprint"):
        assert store.products_of_run(new, "Сбер")[0][field] == store.products_of_run(2, "Сбер")[0][field]
    assert store.coverage_of_run(new)["Сбер"]["Вклады"] == "https://sber.example/deposit"
    assert "partial crawl" in store.conn.execute("SELECT note FROM runs WHERE id=?", (new,)).fetchone()[0]
    store.close()
    with pytest.raises(ValueError, match="Destination changed"):
        merge_bank(dest, source, bank="Сбер", source_run=2, expected_main_run=2, after_source_run=1)


@pytest.mark.parametrize("failure", ["running", "empty", "stale", "schema"])
def test_rejected_merge_does_not_write_partial_snapshot(databases, failure):
    dest, source = databases
    with sqlite3.connect(source) as db:
        if failure == "running":
            db.execute("UPDATE runs SET status='running' WHERE id=2")
        elif failure == "empty":
            db.execute("DELETE FROM products WHERE bank='Сбер' AND run_id=2")
        elif failure == "stale":
            db.execute("UPDATE products SET collected_at='2026-11-09T10:00:00'")
        else:
            db.execute("ALTER TABLE coverage ADD COLUMN unexpected TEXT")
    with pytest.raises(ValueError):
        merge_bank(dest, source, bank="Сбер", source_run=2, expected_main_run=2, after_source_run=1)
    with sqlite3.connect(dest) as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM products WHERE run_id>2").fetchone()[0] == 0

