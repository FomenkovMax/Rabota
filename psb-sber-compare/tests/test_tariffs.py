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
