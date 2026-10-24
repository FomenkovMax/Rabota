import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bankintel.logging_setup import configure_logging, redact

TOKEN = "123456789:AAH-abcdefghijklmnopqrstuvwxyz_0123456"


def test_redact_masks_secrets():
    assert TOKEN not in redact(f"GET https://api.telegram.org/bot{TOKEN}/getMe")
    assert "<telegram-token>" in redact(f"url=bot{TOKEN}/x")
    assert "sk-" not in redact("key sk-abcdefghijklmnopqrstuvwxyz0123456789")
    assert "abcdefghijklmnop" not in redact("Authorization: Bearer abcdefghijklmnop.qrstuv")
    assert redact("обычный текст 12:30 и 123") == "обычный текст 12:30 и 123"  # без ложных срабатываний


def test_filter_masks_message_args_and_traceback(capsys):
    configure_logging("INFO", json_logs=True)
    log = logging.getLogger("t")
    log.info("запрос %s", f"https://x/bot{TOKEN}/send")
    try:
        raise RuntimeError(f"fail bot{TOKEN}")
    except RuntimeError:
        log.exception("сбой")
    err = capsys.readouterr().err
    assert TOKEN not in err and "<telegram-token>" in err
    first = json.loads(err.splitlines()[0])
    assert first["level"] == "INFO" and first["logger"] == "t"
    configure_logging("WARNING", json_logs=False)  # вернуть обычный режим для других тестов


@pytest.fixture
def api(tmp_path, monkeypatch):
    """API на временной SQLite-БД с настоящей схемой."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from bankintel.config import get_settings
    from bankintel.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()

    async def init():
        e = create_async_engine(url)
        async with e.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        await e.dispose()

    asyncio.run(init())
    from bankintel.api.main import app

    yield TestClient(app), url
    get_settings.cache_clear()


def _seed(url, runs):
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from bankintel.db.models import Bank, CollectionRun, Source

    async def go():
        e = create_async_engine(url)
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(e, expire_on_commit=False)() as s:
            b = Bank(slug="psb", name="ПСБ", website="https://www.psbank.ru", adapter="psb")
            s.add(b)
            await s.flush()
            s.add(Source(bank_id=b.id, key="deposits", url="https://www.psbank.ru/x", category="deposit", status="active"))
            for status, age_h in runs:
                s.add(CollectionRun(bank_id=b.id, status=status, started_at=datetime.now(UTC) - timedelta(hours=age_h)))
            await s.commit()
        await e.dispose()

    asyncio.run(go())


def test_health_and_docs_disabled(api):
    client, _ = api
    assert client.get("/health").json()["status"] == "ok"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404  # схему API наружу не отдаём


def test_health_data_fresh_stale_and_never(api):
    client, url = api
    assert client.get("/health/data").json()["status"] == "degraded"  # нет активных источников/данных
    _seed(url, [("ok", 1)])
    d = client.get("/health/data").json()
    assert d["status"] == "ok" and d["banks"][0]["stale"] is False


def test_health_data_marks_stale_and_ignores_failed_runs(api):
    client, url = api
    _seed(url, [("ok", 30), ("failed", 0.1)])  # свежий, но неудачный запуск не освежает данные
    d = client.get("/health/data").json()
    assert d["status"] == "degraded" and d["stale_banks"] == ["psb"] and d["banks"][0]["age_hours"] > 24


def test_noisy_third_party_loggers_are_quiet_at_info_but_not_at_debug():
    configure_logging("INFO")
    assert logging.getLogger("fontTools.subset").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("weasyprint.progress").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("bankintel.cycle").getEffectiveLevel() == logging.INFO      # собственные логи не заглушаем
    configure_logging("DEBUG")
    assert logging.getLogger("fontTools.subset").getEffectiveLevel() == logging.DEBUG    # при отладке доступно всё
    configure_logging("WARNING")
