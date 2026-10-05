import sqlite3
from pathlib import Path

import pytest

from lnrbank.storage.db import RunClosedError, Storage


@pytest.fixture
def store(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "t.db", raw_dir=tmp_path / "raw")
    yield s
    s.close()


def cond(product="SBER-DEP-vklad-1", parameter="rate_12m_online", value="14.2"):
    return dict(
        bank="SBER",
        product_id=product,
        parameter=parameter,
        value=value,
        unit="% годовых",
        condition="онлайн",
        better="higher",
        region_method="selector",
        source_type="page",
        source_url="https://www.sberbank.ru/x",
        evidence="14,2 %",
        confidence="high",
        collected_at="2026-10-05T10:00:00",
    )


def finished_run(store, date, rows=()):
    run = store.start_run("block", ["DEP"], snapshot_date=date)
    store.add_rows("conditions", run, list(rows))
    store.finish_run(run, "ok")
    return run


def test_schema_idempotent_and_wal(tmp_path: Path):
    Storage(tmp_path / "t.db", raw_dir=tmp_path / "raw").close()
    s = Storage(tmp_path / "t.db", raw_dir=tmp_path / "raw")
    assert s.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "runs",
        "banks",
        "infrastructure",
        "products",
        "conditions",
        "scenarios",
        "changes",
        "gaps",
        "data_quality",
        "raw_documents",
        "llm_cache",
    } <= tables
    s.close()


def test_previous_snapshot(store):
    finished_run(store, "2026-10-05")
    finished_run(store, "2026-10-12")
    assert store.latest_snapshot() == "2026-10-12"
    assert store.previous_snapshot() == "2026-10-05"


def test_unfinished_run_not_a_snapshot(store):
    finished_run(store, "2026-10-05")
    store.start_run("block", ["DEP"], snapshot_date="2026-10-12")
    assert store.latest_snapshot() == "2026-10-05"


def test_duplicate_condition_rejected(store):
    run = store.start_run("block", ["DEP"], snapshot_date="2026-10-05")
    store.add_rows("conditions", run, [cond()])
    with pytest.raises(sqlite3.IntegrityError):
        store.add_rows("conditions", run, [cond()])


def test_write_to_finished_run_forbidden(store):
    run = finished_run(store, "2026-10-05")
    with pytest.raises(RunClosedError):
        store.add_rows("conditions", run, [cond()])


def test_unknown_column_or_table_rejected(store):
    run = store.start_run("block", ["DEP"], snapshot_date="2026-10-05")
    with pytest.raises(ValueError):
        store.add_rows("conditions", run, [{**cond(), "evil; DROP TABLE runs": 1}])
    with pytest.raises(ValueError):
        store.add_rows("sqlite_master", run, [{}])


def test_rows_by_snapshot(store):
    finished_run(store, "2026-10-05", [cond(value="14.0")])
    finished_run(store, "2026-10-12", [cond(value="14.3")])
    assert [r["value"] for r in store.rows("conditions", "2026-10-12")] == ["14.3"]


def test_raw_document_saved_with_hash(store):
    run = store.start_run("block", ["DEP"], snapshot_date="2026-10-05")
    doc = store.save_raw_document(
        run, "PSB", "https://www.psbank.ru/a", "html", b"<p>x</p>", region_method="selector"
    )
    assert Path(doc["path"]).read_bytes() == b"<p>x</p>"
    assert len(doc["sha256"]) == 64
    assert "2026-10-05" in doc["path"] and "PSB" in doc["path"]


def test_retention_removes_files_keeps_data(store):
    r1 = store.start_run("block", ["DEP"], snapshot_date="2026-10-05")
    d1 = store.save_raw_document(r1, "SBER", "https://u", "html", b"a", region_method="selector")
    store.add_rows("conditions", r1, [cond()])
    store.finish_run(r1, "ok")
    r2 = store.start_run("block", ["DEP"], snapshot_date="2026-10-12")
    d2 = store.save_raw_document(r2, "SBER", "https://u", "html", b"b", region_method="selector")
    store.finish_run(r2, "ok")
    store.prune_raw(keep_snapshots=1)
    assert not Path(d1["path"]).exists() and Path(d2["path"]).exists()
    assert len(store.rows("conditions", "2026-10-05")) == 1


def test_llm_cache(store):
    store.cache_put("abc", "v1", "GigaChat-Max", {"items": [1]})
    assert store.cache_get("abc", "v1", "GigaChat-Max") == {"items": [1]}
    assert store.cache_get("abc", "v2", "GigaChat-Max") is None


def test_rerun_same_day_replaces_values(store):
    finished_run(store, "2026-10-05", [cond(value="14.0")])
    finished_run(store, "2026-10-05", [cond(value="14.3")])
    assert [r["value"] for r in store.rows("conditions", "2026-10-05")] == ["14.3"]


def test_derived_tables_replaced_on_rerun(store):
    for _ in range(2):
        run = store.start_run("block", ["DEP"], snapshot_date="2026-10-05")
        store.add_rows("data_quality", run, [dict(bank="SBER", block="DEP", coverage_pct=80.0)])
        store.finish_run(run, "ok")
    assert len(store.rows("data_quality", "2026-10-05")) == 1
