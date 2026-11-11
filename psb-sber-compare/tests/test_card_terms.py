"""Параметры карт: обслуживание, кешбэк, переводы, беспроцентный период."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import card_terms as ct
from src.banks.seo import is_seo_page


def test_debit_card_terms():
    lines = ["Бесплатное обслуживание и кешбэк", "Получайте до 10% бонусами Спасибо",
             "А ещё ловите суперкешбэк до 50% в разделе «Для жизни»",
             "— Максимальная сумма кешбэка в месяц — 3 000 ₽",
             "Переводы без комиссии до 100 000 ₽ в месяц"]
    out = ct.extract(lines)
    assert out == {ct.SERVICE: "бесплатно", ct.CASHBACK: "10 %",
                   ct.CASHBACK_CAP: "3 000 ₽", ct.TRANSFERS: "до 100 000 ₽ в месяц"}


def test_service_price_and_spend_condition():
    assert ct.extract(["Ежемесячное обслуживание**", "90 ₽ в месяц"])[ct.SERVICE] == "90 ₽ в месяц"
    # Условие бесплатности по тратам — не цена обслуживания.
    assert ct.SERVICE not in ct.extract(["Обслуживание", "при тратах от 1 000 000 ₽ в месяц"])


def test_credit_card_grace_and_summary():
    out = ct.extract(["до 120 дней без %", "0 ₽ за обслуживание", "до 10% кешбэка"])
    assert out[ct.GRACE] == "до 120 дней" and out[ct.SERVICE] == "бесплатно"
    assert ct.summary(out) == "обсл. бесплатно · кешбэк до 10 % · без % до 120 дней"


def test_tbank_city_black_pages_are_seo():
    assert is_seo_page("https://www.tbank.ru/cards/debit-cards/tinkoff-black/moskva")
    assert not is_seo_page("https://www.tbank.ru/cards/debit-cards/tinkoff-black/junior")
    assert not is_seo_page("https://www.tbank.ru/cards/debit-cards/tinkoff-black")
