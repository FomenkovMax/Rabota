from decimal import Decimal as D

import pytest

from bankintel.analytics.parsing import MoneyRange, TermSpec, parse_money_range, parse_term


# Строки ниже — реальные значения с сайтов ПСБ/ВТБ (24.10.2026)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("От 50 000 ₽", MoneyRange(D(50000), None, "RUB")),
        ("От 10 000 ₽ до 150 000 ₽", MoneyRange(D(10000), D(150000), "RUB")),
        ("От 50 000 ₽ до 10 000 000 ₽", MoneyRange(D(50000), D(10_000_000), "RUB")),
        ("От\xa0300\xa0000 ₽ до 10 млн ₽", MoneyRange(D(300000), D(10_000_000), "RUB")),
        ("От 50 тыс. ₽ до 10 млн ₽", MoneyRange(D(50000), D(10_000_000), "RUB")),
        ("От 0.01 ₽ до 50 000 ₽", MoneyRange(D("0.01"), D(50000), "RUB")),
        ("До 50 000 ₽", MoneyRange(None, D(50000), "RUB")),
        ("От 1 000 Ұ", MoneyRange(D(1000), None, "CNY")),
        ("От 10 000 ¥", MoneyRange(D(10000), None, "CNY")),
    ],
)
def test_money(text, expected):
    assert parse_money_range(text) == expected


@pytest.mark.parametrize("text", [None, "", "Без ограничений", "Начисление %"])
def test_money_unparsed(text):
    assert parse_money_range(text) is None


@pytest.mark.parametrize(
    "text,spec",
    [
        ("91, 181 и 367 дней", TermSpec(values=(91, 181, 367))),
        ("32, 91, 122 дня", TermSpec(values=(32, 91, 122))),
        ("От 91 до 731 дня", TermSpec(min_days=91, max_days=731)),
        ("От 32 до 367 дня", TermSpec(min_days=32, max_days=367)),
        ("91 – 731 дней", TermSpec(min_days=91, max_days=731)),
        ("91–367 дней", TermSpec(min_days=91, max_days=367)),
        ("365 дней", TermSpec(values=(365,))),
        ("2-36 мес.", TermSpec(min_days=61, max_days=1095)),
        ("3, 6, 12 мес.", TermSpec(values=(91, 183, 365))),
        ("1 год", TermSpec(values=(365,))),
        ("3 мес.", TermSpec(values=(91,))),
    ],
)
def test_term(text, spec):
    assert parse_term(text) == spec


@pytest.mark.parametrize("text", [None, "", "До двух лет", "До 2 лет", "Бессрочно", "Начисление %"])
def test_term_unparsed_is_none(text):
    assert parse_term(text) is None


def test_term_allows():
    rng = TermSpec(min_days=91, max_days=731)
    assert rng.allows(91) and rng.allows(365) and not rng.allows(90)
    discrete = TermSpec(values=(91, 181, 367))
    assert discrete.allows(183) and discrete.allows(365)  # допуск на округление месяцев
    assert not discrete.allows(270)
