"""Бот: разбор категории и аргументы для клиента — только из данных."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from bot import keyboards, service
from src import market


def _data():
    def offer(bank, value, title):
        return market.Offer(bank, value, title, f"https://{bank}/x")

    behind = market.Gap(block="DEP", program="Накопительные счета", metric="rate_max",
                        better="higher", category="Накопительные счета")
    behind.offers = [offer("ЦМР", 13.5, "Больше чем счёт"), offer("Сбер", 12.5, "Накопительный")]
    behind.sber, behind.best = behind.offers[1], behind.offers[0]
    behind.rank, behind.banks_compared, behind.status = 2, 2, market.BEHIND
    behind.others_median = 13.5

    leader = market.Gap(block="DEP", program="Вклады", metric="rate_max", better="higher",
                        category="Вклады")
    leader.offers = [offer("Сбер", 14.8, "Лучший % Золотой"), offer("ПСБ", 14.5, "Мой доход")]
    leader.sber, leader.best = leader.offers[0], leader.offers[0]
    leader.rank, leader.banks_compared, leader.status = 1, 2, market.LEADER
    leader.others_median = 14.5

    special = market.SpecialRow(
        bank="ВТБ", category="Накопительные счета", program="Накопительные счета",
        title="Накопительный ВТБ-Счет", rate=14.2, kind="welcome",
        kind_label="приветственная / для новых клиентов", reason="первые 2 месяца", url="")
    return {"gaps": [behind, leader], "specials": [special], "home_title": "Сбер",
            "collected_at": "2026-10-07 10:00", "region": "ЛНР"}


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    monkeypatch.setattr(service, "load_report_data", lambda config: _data())
    monkeypatch.setattr(service, "_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service.consultant, "available", lambda: False)


def test_category_text_shows_place_and_specials():
    text = service.category_text("sav")
    assert "Накопительные счета" in text and "отстаёт" in text
    assert "ЦМР до 13,5 %" in text
    assert "ВТБ" in text and "приветственная" in text


def test_template_script_is_honest_when_behind():
    text = service.client_script("sav")
    assert "у ЦМР базовая ставка до 13,5 %, у Сбера до 12,5 %" in text
    # Аргумента по ставке в данных нет — так и сказано, без выдуманных достоинств.
    assert "аргумента по ставке в данных нет" in text
    assert "ВТБ" in text and "приветственная" in text


def test_template_script_states_lead_with_numbers():
    text = service.client_script("dep")
    assert "у Сбера до 14,8 %" in text and "место 1" in text


def test_menus_have_category_filter_and_audit():
    codes = {b.callback_data for row in keyboards.main_menu().inline_keyboard for b in row}
    assert {"cat:menu", "audit:menu"} <= codes
    assert len(keyboards.category_menu().inline_keyboard) == len(keyboards.CATEGORY_BUTTONS) + 1
