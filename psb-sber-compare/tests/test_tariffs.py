"""Ставка из PDF-тарифа: ссылки на тарифы и разбор текста."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import tariffs


def test_tariff_links_skip_requirements_and_loyalty():
    base = "https://cdn.tbank.ru/static/documents/"
    links = [[base + "doc-requirements-for-real-estate-to-cash-loan.pdf", "Требования"],
             [base + "loyalty-program-black.pdf", "Правила программы"],
             [base + "loans-cashloan-tariff-2x.pdf", ""],
             [base + "5b0c1da5.pdf", "Тарифы по кредиту"],
             ["https://www.tbank.ru/loans/cash-loan", "Кредит"]]
    assert tariffs.tariff_links(links) == [base + "loans-cashloan-tariff-2x.pdf",
                                           base + "5b0c1da5.pdf"]


def test_rate_from_tariff_text():
    text = ("Тарифный план КН 2.0\n"
            "Полная стоимость кредита 19,9% — 64,9%\n"
            "Неустойка при неоплате минимального платежа 20% годовых\n"
            "Процентная ставка: от 19,9% до 54,9% годовых\n")
    assert tariffs.rate_from_text(text) == (19.9, 54.9, "Процентная ставка: от 19,9% до 54,9%")
    assert tariffs.rate_from_text("Неустойка — ставка 0,1% в день") is None


def test_tariff_heading_with_colon_and_long_note():
    """Кредитки Т-Банка (29.10.2026): «1. Процентная ставка:», подпункты,
    пояснение про беспроцентный период, «0% годовых», затем диапазон до 61,9%."""
    text = ("1. Процентная ставка:\n1.1. на покупки в беспроцентный период до 55 дней\n"
            "1.2. на покупки\nПроценты не начисляются, если:\n— платеж внесен вовремя.\n"
            "0% годовых\nот\xa029,9% до\xa061,9% годовых\n2. Плата за обслуживание\n")
    assert tariffs.rate_from_text(text, ceiling=70) == (
        29.9, 61.9, "1. Процентная ставка: от 29,9% до 61,9% годовых")


def test_tariff_range_without_first_percent():
    """Автокредит Т-Банка: «от 0,01 до 31,0% годовых» — знак только у второго числа."""
    text = ("1. Процентная ставка\n1.1. Базовая\n1.2. Повышенная\n"
            "от 0,01 до 31,0% годовых\n+ 15 процентных пунктов\n2. Плата за услуги\n")
    assert tariffs.rate_from_text(text)[:2] == (0.01, 31.0)
    # Голое число без процента под заголовком — не ставка.
    assert tariffs.rate_from_text("1. Процентная ставка\n55\n2. Плата\n") is None
