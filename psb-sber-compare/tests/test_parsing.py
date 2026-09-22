"""Тесты разбора чисел и логики светофора.

Проверяем ровно те формулировки, которые реально встречаются на сайте ПСБ:
именно на них наивный разбор и ломается.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.compare import GREEN, GREY, RED, YELLOW, Comparison, Thresholds, _evaluate, normalize_title
from src.psb.parser import Product, parse_money, parse_rates, parse_term_months
from src.psb.state import clean


# --- ставки ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("от 16,9%", [16.9]),
    ("16,901% — 36,999%", [16.901, 36.999]),
    ("18,75 % — 23,89 %", [18.75, 23.89]),
    ("до 13,5%", [13.5]),
    ("ставка не указана", []),
])
def test_parse_rates(text, expected):
    assert parse_rates(text) == expected


# --- суммы ----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # Единица только у верхней границы — нижнюю терять нельзя.
    ("От 100 000 — 5 000 000 ₽", [100_000.0, 5_000_000.0]),
    ("До 10 млн ₽", [10_000_000.0]),
    # Полностью записанное число не должно наследовать «млн» соседа.
    ("От 30 000 до 1,5 млн рублей", [30_000.0, 1_500_000.0]),
    ("От 500 тыс до 30 млн ₽", [500_000.0, 30_000_000.0]),
    # Без валюты это не сумма.
    ("от 36 до 84 месяцев", []),
])
def test_parse_money(text, expected):
    assert parse_money(text) == expected


# --- сроки ----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("От 36 до 84 месяцев", [36, 84]),
    ("До 10 лет", [120]),
    ("от 3 до 36 мес", [3, 36]),
    ("сумма 100 000 ₽", []),
])
def test_parse_term_months(text, expected):
    assert parse_term_months(text) == expected


# --- очистка текста -------------------------------------------------------

def test_clean_strips_tags_and_entities():
    raw = 'От&nbsp;100&nbsp;000 <a class="tooltip" title-tooltip="подсказка"></a>₽'
    assert clean(raw) == "От 100 000 ₽"


# --- нормализация названий ------------------------------------------------

def test_normalize_title_drops_bank_noise():
    assert normalize_title("Автокредит в ПСБ") == "автокредит"
    assert normalize_title("Кредит наличными") == normalize_title("КРЕДИТ  НАЛИЧНЫМИ")


# --- светофор -------------------------------------------------------------

def _pair(psb_rate, sber_rate, category=""):
    """Простая пара: диапазон схлопнут в одну точку."""
    comparison = Comparison(
        pair_id="t", label="Тест", category=category,
        psb=Product(rate_min=psb_rate, rate_max=psb_rate),
        sber=Product(rate_min=sber_rate, rate_max=sber_rate),
    )
    _evaluate(comparison, Thresholds(parity=0.5, loss=1.0))
    return comparison


def test_credit_compares_lower_bound():
    """По кредиту сравнивается витринная ставка «от», то есть минимум."""
    comparison = Comparison(
        pair_id="t", label="Тест", category="Кредиты",
        psb=Product(rate_min=16.9, rate_max=36.9),
        sber=Product(rate_min=18.9, rate_max=33.2),
    )
    _evaluate(comparison, Thresholds())
    assert comparison.delta_rate == pytest.approx(2.0)
    assert comparison.light == RED


def test_deposit_compares_upper_bound():
    """По вкладу банк рекламирует «до», поэтому сравнивается максимум.

    Если бы сравнивался минимум (11,0 против 13,5), вердикт был бы
    «выигрываем» — прямо противоположный правильному.
    """
    comparison = Comparison(
        pair_id="t", label="Вклад", category="Вклады",
        psb=Product(rate_min=11.0, rate_max=13.8),
        sber=Product(rate_min=11.0, rate_max=13.5),
    )
    _evaluate(comparison, Thresholds())
    assert comparison.delta_rate == pytest.approx(-0.3)
    assert comparison.light == YELLOW


def test_credit_lower_rate_wins():
    """По кредиту выгода клиента — ставка ниже."""
    assert _pair(18.0, 16.0, "Кредиты").light == GREEN
    assert _pair(16.0, 18.0, "Кредиты").light == RED


def test_deposit_higher_rate_wins():
    """По вкладу всё наоборот: выгодна ставка выше."""
    assert _pair(12.0, 14.0, "Вклады").light == GREEN
    assert _pair(14.0, 12.0, "Вклады").light == RED


def test_parity_band():
    assert _pair(16.0, 16.3, "Кредиты").light == YELLOW
    assert _pair(16.0, 15.7, "Кредиты").light == YELLOW


def test_small_loss_is_not_red():
    """Отставание меньше порога проигрыша — жёлтый, не красный."""
    assert _pair(16.0, 16.8, "Кредиты").light == YELLOW


def test_missing_rate_is_grey():
    assert _pair(None, 16.0, "Кредиты").light == GREY
    assert _pair(16.0, None, "Кредиты").light == GREY


def test_missing_product_is_grey():
    comparison = Comparison(pair_id="t", label="Тест", category="Кредиты", psb=None, sber=None)
    _evaluate(comparison, Thresholds())
    assert comparison.light == GREY


def test_delta_sign_is_sber_minus_psb():
    assert _pair(16.0, 18.0, "Кредиты").delta_rate == 2.0
    assert _pair(18.0, 16.0, "Кредиты").delta_rate == -2.0


# --- слепок продукта ------------------------------------------------------

def test_fingerprint_changes_with_terms():
    a = Product(rate_raw="от 16,9%", terms={"Срок": "36 мес"})
    b = Product(rate_raw="от 16,9%", terms={"Срок": "48 мес"})
    assert a.fingerprint() != b.fingerprint()


def test_fingerprint_stable_when_nothing_changed():
    a = Product(rate_raw="от 16,9%", terms={"Срок": "36 мес"})
    b = Product(rate_raw="от 16,9%", terms={"Срок": "36 мес"})
    assert a.fingerprint() == b.fingerprint()
