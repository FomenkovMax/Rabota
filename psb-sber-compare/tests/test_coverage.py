"""Матрица охвата «банк × категория» (аудит 07.10.2026)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src import coverage
from src.storage import Storage


@pytest.mark.parametrize("url, category", [
    ("https://www.vtb.ru/personal/vklady-i-scheta/vtb-vklad-r", "Вклады"),
    ("https://www.vtb.ru/personal/vklady-i-scheta/invest-plus", "Вклады"),
    ("https://www.vtb.ru/personal/vklady-i-scheta/nakopitelnyi-schet", "Накопительные счета"),
    ("https://www.vtb.ru/personal/vklady-i-scheta/seyfovye-yacheyki", "Сейфовые ячейки"),
    ("https://www.vtb.ru/personal/karty/kreditnye", "Кредитные карты"),
    ("https://www.vtb.ru/personal/kredit/pod-zalog-avto", "Потребительские кредиты"),
    ("https://www.vtb.ru/personal/investicii/", "Инвестиции"),
    ("https://www.sberbank.ru/ru/person/bank_cards/credit", "Кредитные карты"),
    ("https://www.sberbank.ru/ru/person/credits/home/family", "Ипотека"),
    ("https://www.sberbank.ru/ru/person/investments", "Инвестиции"),
    ("https://www.sberbank.ru/ru/person/contributions/deposits/vklady-dolgosrochnye", "Вклады"),
    ("https://www.tbank.ru/loans/auto-loan", "Автокредиты"),
    ("https://www.tbank.ru/insurance/mortgage", "Страхование"),
    ("https://www.tbank.ru/payments/card-to-card", "Переводы и платежи"),
    ("https://www.psbank.ru/personal/pds/dolgosrochnyye-sbyeryezhyeniya", "НПФ и ПДС"),
    ("https://www.psbank.ru/personal/creditcards/100_plus", "Кредитные карты"),
    ("https://cmrbank.ru/person/person-deposit/", "Вклады"),
    ("https://cmrbank.ru/person/obmen-valjuty/", "Валютные операции"),
    ("https://cmrbank.ru/person/payments-and-transfers/", "Переводы и платежи"),
])
def test_classify(url, category):
    assert coverage.classify(url) == category


@pytest.mark.parametrize("url", [
    "https://cdn.tbank.ru/static/documents/deposit-smartdeposit.pdf",
    "https://online.vtb.ru/debit-card/step1/deposit",
    "https://www.sberbank.ru/ru/s_m_business/credits",
    "https://www.vtb.ru/personal/news/",
    "https://www.vtb.ru/",
])
def test_not_a_retail_section(url):
    assert coverage.classify(url) is None


def test_collect_keeps_section_root_and_own_site():
    found = {}
    coverage.collect(["https://www.psbank.ru/personal/cards/offers/credit-card-cashback",
                      "https://www.psbank.ru/personal/creditcards",
                      "https://www.vtb.ru/personal/ipoteka"],
                     found, base_url="https://www.psbank.ru")
    assert found == {"Кредитные карты": "https://www.psbank.ru/personal/creditcards"}


def test_matrix_statuses():
    def product(bank, category, rate, title="Продукт"):
        return SimpleNamespace(bank=bank, category=category, title=title, rate_min=rate,
                               rate_max=rate, source_url=f"https://{bank}/p")

    products = [product("Сбер", "Вклады", 14.0), product("ПСБ", "Страхование", None),
                product("Сбер", "Кредиты", 20.0, "Автокредит")]
    links = {"Сбер": {"Инвестиции": "https://sber/invest"}}
    m = coverage.matrix(["Сбер", "ПСБ"], products, links)
    assert m["Вклады"]["Сбер"].status == coverage.COMPARED
    assert m["Страхование"]["ПСБ"].status == coverage.COLLECTED
    assert m["Инвестиции"]["Сбер"].status == coverage.LINK_ONLY
    assert m["Инвестиции"]["ПСБ"].status == coverage.NOT_FOUND
    assert m["Автокредиты"]["Сбер"].status == coverage.COMPARED


def test_coverage_is_stored_and_carried_over(tmp_path):
    storage = Storage(tmp_path / "t.db")
    first = storage.start_run("ЛНР")
    storage.save_coverage(first, "ВТБ", {"Инвестиции": "https://vtb/invest"})
    storage.save_coverage(first, "Сбер", {"Вклады": "https://sber/vklad"})
    second = storage.start_run("ЛНР")
    storage.carry_over(first, second, except_bank="Сбер")
    assert storage.coverage_of_run(second) == {"ВТБ": {"Инвестиции": "https://vtb/invest"}}
