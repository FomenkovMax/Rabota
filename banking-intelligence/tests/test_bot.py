from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from bankintel.bot import handlers, views
from bankintel.bot.access import AllowlistMiddleware
from bankintel.bot.app import build_dispatcher
from bankintel.config import Settings
from bankintel.db.models import Bank, CollectionRun


def msg(user_id=1):
    from aiogram.types import Message

    m = AsyncMock(spec=Message)
    m.from_user = SimpleNamespace(id=user_id)
    m.answer = AsyncMock()
    return m


async def test_start_warns_about_demo():
    m = msg()
    await handlers.cmd_start(m)
    assert "Демо-прототип" in m.answer.call_args.args[0]


async def test_banks_lists_all_and_flags_unverified(seeded):
    m = msg()
    await handlers.cmd_banks(m, session_factory=seeded)
    text = m.answer.call_args.args[0]
    for name in ("Сбербанк", "ПСБ", "ВТБ", "Генбанк", "ЦМР банк"):
        assert name in text
    assert "не подтвержден" in text and "⭐" in text
    assert "✅" not in text


async def test_status_reports_no_collection(seeded):
    m = msg()
    await handlers.cmd_status(m, session_factory=seeded)
    text = m.answer.call_args.args[0]
    assert text.count("сбор не запускался") == 5


async def test_status_shows_last_run(seeded):
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        s.add(CollectionRun(bank_id=bank.id, started_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC), status="failed"))
        await s.commit()
        text = await views.status_text(s)
    assert "02.01.2026 03:04: failed" in text


async def test_html_is_escaped(session_factory):
    async with session_factory() as s:
        s.add(Bank(slug="x", name="<b>X&Y", website="https://x.ru", adapter="generic"))
        await s.commit()
        text = await views.banks_text(s)
    assert "&lt;b&gt;X&amp;Y" in text


def test_planned_commands_registered_and_honest():
    for cmd in views.PLANNED:
        assert "пока не реализовано" in views.planned_text(cmd)
    assert len(handlers.router.message.handlers) == 3 + len(views.PLANNED)


async def test_allowlist_blocks_and_allows():
    mw = AllowlistMiddleware([42])
    handler = AsyncMock(return_value="ok")
    denied = msg(7)
    assert await mw(handler, denied, {}) is None
    handler.assert_not_called()
    denied.answer.assert_awaited()
    assert await mw(handler, msg(42), {}) == "ok"


async def test_empty_allowlist_denies_everyone():
    handler = AsyncMock()
    assert await AllowlistMiddleware([])(handler, msg(1), {}) is None
    handler.assert_not_called()


def test_dispatcher_builds():
    build_dispatcher([1], session_factory=None)


def test_settings_parse_ids_and_hide_secret(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "1, 2,3")
    monkeypatch.setenv("BOT_TOKEN", "123:secret")
    s = Settings(_env_file=None)
    assert s.allowed_telegram_ids == [1, 2, 3]
    assert "secret" not in repr(s)


def test_empty_env_values_mean_unset(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "")
    s = Settings(_env_file=None)
    assert s.bot_token is None and s.allowed_telegram_ids == []


def test_env_example_parses_to_unset():
    from pathlib import Path

    s = Settings(_env_file=Path(__file__).parents[1] / ".env.example")
    assert s.bot_token is None and s.openai_api_key is None
