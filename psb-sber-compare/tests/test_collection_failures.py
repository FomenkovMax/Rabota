from datetime import datetime
from types import SimpleNamespace

import pytest

from src import pipeline
from src.psb.parser import Product
from src.storage import Storage


@pytest.mark.parametrize("all_failed", [False, True])
def test_failed_bank_keeps_previous_products_and_all_failed_run_is_not_success(tmp_path, monkeypatch, all_failed):
    db = tmp_path / "banks.db"
    config = pipeline.Config({"storage": {"db_path": str(db)},
                              "notify": {"digest_file": str(tmp_path / "digest.txt")}})
    with_storage = Storage(db)
    old = with_storage.start_run("ЛНР")
    with_storage.save_products(old, [
        Product(bank="Сбер", title="Вклад", category="Вклады", rate_min=10,
                source_url="https://bank.example/deposit", collected_at=datetime.now().isoformat()),
    ])
    with_storage.finish_run(old, psb=0, sber=1, promos=0)
    with_storage.close()
    failed = SimpleNamespace(ok=False, bank="Сбер", summary="Сбер — ошибка чтения")
    rival = SimpleNamespace(ok=not all_failed, bank="ВТБ", summary="ВТБ",
                            products=[Product(bank="ВТБ", title="Вклад", category="Вклады", rate_min=11)],
                            promos=[], coverage={}, partial=False)
    monkeypatch.setattr(pipeline, "collect_all", lambda config: {"sber": failed, "vtb": rival})
    monkeypatch.setattr(pipeline.keyrate, "fetch", lambda config: None)
    monkeypatch.setattr(pipeline, "load_report_data", lambda config: None)
    monkeypatch.setattr(pipeline, "_mark_region", lambda result: None)
    result = pipeline.run(config)
    storage = Storage(db)
    try:
        assert len(storage.products_of_run(result["run_id"], bank="Сбер")) == 1
        assert storage.last_successful_run_id() == (old if all_failed else result["run_id"])
        assert result["failures"]
    finally:
        storage.close()
