from decimal import Decimal as D
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import CommandObject
from sqlalchemy import select
from test_analytics import NOW, _psb_facts, _vtb_facts

from bankintel.analytics.compare import Scenario, compare
from bankintel.bot import handlers
from bankintel.bot.compare_views import compare_text, deposits_text, money, parse_scenario, pct, savings_text
from bankintel.collector import collect_bank
from bankintel.db.models import Bank
from bankintel.domain.enums import FetchOutcome
from bankintel.sources.base import FetchDiagnostic, FetchedDocument

FIX = Path(__file__).parent / "fixtures"


def test_formatting():
    assert money(D("70500.00")) == "70 500 ₽"
    assert money(D("3739.73")) == "3 739,73 ₽"
    assert pct(D("14.10")) == "14,1%" and pct(D("15")) == "15%" and pct(D("12.00")) == "12%"


def test_parse_scenario():
    assert parse_scenario(None) == Scenario(D(500_000), 12)
    assert parse_scenario("1000000 6") == Scenario(D(1_000_000), 6)
    assert parse_scenario("1_000_000 6").amount == D(1_000_000)
    for bad in ("abc", "500000", "500000 0", "500000 61", "5 12", "5000000000 12", "100 000 12"):
        with pytest.raises(ValueError):
            parse_scenario(bad)


def test_compare_text_is_honest():
    facts = _psb_facts() + _vtb_facts()
    rep = compare(facts, Scenario(D(100_000), 3), all_banks=[("sber", "Сбербанк"), ("psb", "ПСБ"), ("vtb", "ВТБ")], now=NOW)
    text = compare_text(rep)
    assert "простой процент" in text and "диапазоны" in text          # метод и неопределённость названы
    assert "Сбербанк</b> — данных нет" in text                          # эталон отсутствует — прямо сказано
    assert "ЛНР не подтверждена" in text
    assert "Топ-5 вкладов для всех" in text and "С особыми условиями" in text and "Исключено" in text
    assert len(text) < 4096


def test_catalogs():
    facts = _psb_facts() + _vtb_facts()
    t = deposits_text(facts)
    assert "Мой доход" in t and "12–14,1%" not in t and "12%–14,1%" in t
    assert "до 18%" in t and "👥" in t and "📈" in t and "ЛНР" in t
    assert "Данных нет" in savings_text([])


class _PageFetcher:
    """Подмена загрузчика: отдаёт фрагменты реальных страниц (без сети)."""

    async def fetch(self, source):
        name = "psb_savings_cards.html" if source.key == "savings_accounts" else "psb_deposits_cards.html"
        return FetchedDocument(source.url, (FIX / name).read_bytes(), "text/html"), FetchDiagnostic(
            source.key, source.url, FetchOutcome.OK, 200
        )


async def _collect_psb(seeded, tmp_path):
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        await collect_bank(s, bank, _PageFetcher(), tmp_path)


async def test_handlers_end_to_end_from_db(seeded, tmp_path):
    await _collect_psb(seeded, tmp_path)
    m = AsyncMock()
    await handlers.cmd_compare(m, CommandObject(command="compare", args="100000 6"), session_factory=seeded)
    text = m.answer.call_args.args[0]
    assert "100 000 ₽ на 6 мес." in text and "ПСБ" in text
    assert "Сбербанк</b> — данных нет" in text and "ВТБ</b> — данных нет" in text
    m = AsyncMock()
    await handlers.cmd_deposits(m, session_factory=seeded)
    assert "Мой доход" in m.answer.call_args.args[0]
    m = AsyncMock()
    await handlers.cmd_savings(m, session_factory=seeded)
    assert "Акцент на процент" in m.answer.call_args.args[0] and "базовая 5%" in m.answer.call_args.args[0]


async def test_compare_rejects_bad_args_without_db(seeded):
    m = AsyncMock()
    await handlers.cmd_compare(m, CommandObject(command="compare", args="foo bar"), session_factory=seeded)
    assert "Сумма и срок должны быть числами" in m.answer.call_args.args[0]
    m = AsyncMock()
    await handlers.cmd_compare(m, CommandObject(command="compare", args="foo"), session_factory=seeded)
    text = m.answer.call_args.args[0]
    assert "&lt;сумма в ₽&gt;" in text and "<сумма" not in text  # HTML экранирован


async def test_compare_on_empty_db(seeded):
    m = AsyncMock()
    await handlers.cmd_compare(m, CommandObject(command="compare", args=None), session_factory=seeded)
    text = m.answer.call_args.args[0]
    assert "Подходящих вкладов без особых условий" in text and "данных нет" in text
