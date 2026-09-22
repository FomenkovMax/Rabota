"""Тесты классификации акций.

Проверяем те формулировки, на которых наивный разбор ошибается, —
все они взяты с реальных страниц ПСБ.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.promos import (
    ACTIVE, BONUS_SEGMENT, CASHBACK, DISCOUNT, EXPIRED, OTHER_SEGMENT, POINTS,
    PRIZE, RATE, UNDATED, PromoInsight, classify, compare_segments, format_benefit,
    is_offer, parse_benefit, parse_valid_until, segment_of, sort_key, status_of,
)

TODAY = date(2026, 9, 22)


# --- отсев не-акций -------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Что такое акции и зачем в них инвестировать",
    "Когда растут цены на акции",
    "Как заработать на акциях",
    "Инвестируйте в акции и облигации",
    "Мы продлили срок действия карт",
    "Как подключить бонусную программу",
])
def test_articles_are_not_offers(title):
    """Омоним «акции» тащит в выборку статьи про ценные бумаги."""
    assert is_offer(title) is False


@pytest.mark.parametrize("title", [
    "Кешбэк от ПСБ: 30% на общественный транспорт",
    "Акция «Друг за Друга»",
    "Дебетовая карта с кешбэком 9000 ₽",
])
def test_real_offers_pass(title):
    assert is_offer(title) is True


# --- актуальность ---------------------------------------------------------

def test_expired_by_end_date():
    status, until = status_of(
        "Акция действует с 02 октября 2023 по 31 марта 2024", "", today=TODAY)
    assert status == EXPIRED
    assert until == date(2024, 3, 31)


def test_expired_by_explicit_word():
    status, until = status_of(
        "2000 баллов за оплату", "Акция завершена 30.06.2026", today=TODAY)
    assert status == EXPIRED
    assert until == date(2026, 6, 30)


def test_active_when_end_date_ahead():
    status, until = status_of("Кешбэк 10%", "Акция действует до 31.12.2026", today=TODAY)
    assert status == ACTIVE
    assert until == date(2026, 12, 31)


def test_eligibility_date_is_not_expiry():
    """«Для карт, полученных до 31 января 2024» — условие, а не срок.

    Принимая такую дату за окончание, инструмент объявлял бы завершённой
    действующую акцию.
    """
    status, until = status_of(
        "Акция «Праздники вместе с ПСБ»",
        "Для владельцев кредитных карт, полученных до 31 января 2024",
        today=TODAY,
    )
    assert status == UNDATED
    assert until is None


def test_call_to_action_deadline_counts():
    status, _ = status_of(
        "Дарим подарок", "Откройте счёт до 31 января 2025", today=TODAY)
    assert status == EXPIRED


def test_year_missing_is_not_expired():
    """Без года судить нельзя — не отсеиваем."""
    status, until = status_of("Акция", "Акция действует до 31 октября", today=TODAY)
    assert status == UNDATED
    assert until is None


def test_no_date_is_undated():
    assert status_of("Кешбэк 7% на спорт", "", today=TODAY)[0] == UNDATED


# --- выгода ---------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Кешбэк 30% на общественный транспорт", (CASHBACK, 30.0, "%")),
    # Кешбэк бывает и в рублях — единица не выводится из типа.
    ("Дебетовая карта с кешбэком 9000 ₽", (CASHBACK, 9000.0, "₽")),
    ("400 руб. скидка на первую покупку", (DISCOUNT, 400.0, "₽")),
    ("Получите до 2000 баллов", (POINTS, 2000.0, "баллов")),
    ("Розыгрыш 1 000 000 ₽", (PRIZE, 1000000.0, "₽")),
    # Рубли в строке есть, но речь про ставку.
    ("Снизим ставку до 5% при оформлении кредита на сумму от 1 млн ₽",
     (RATE, 5.0, "%")),
])
def test_parse_benefit(title, expected):
    assert parse_benefit(title) == expected


def test_format_benefit_units():
    assert format_benefit(30.0, "%") == "30 %"
    assert format_benefit(9000.0, "₽") == "9 000 ₽"
    assert format_benefit(2000.0, "баллов") == "2 000 баллов"


# --- сегменты -------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/personal/debetcards/mir-cashback", "Дебетовые карты"),
    ("/personal/creditcards/with-cashback", "Кредитные карты"),
    ("/personal/loans/kredit-na-remont", "Кредиты"),
    ("/personal/pensioncards/pensionaction", "Пенсионные карты"),
])
def test_segment_from_section(path, expected):
    assert segment_of(path, "любой заголовок") == expected


def test_segment_falls_back_to_benefit_type():
    """Акция в корне /personal к продукту не привязана, но тип выгоды известен."""
    assert segment_of("/personal/domashniy-cashback", "Домашний кешбэк",
                      benefit_type=CASHBACK) == BONUS_SEGMENT


def test_unknown_stays_other():
    assert segment_of("/personal/salyut", "Акция «Салют»") == OTHER_SEGMENT


# --- сравнение сегментов --------------------------------------------------

def _promo(bank, segment, benefit_type, value, unit, title="x"):
    return PromoInsight(bank=bank, title=title, segment=segment,
                        benefit_type=benefit_type, benefit_value=value,
                        benefit_unit=unit)


def test_higher_cashback_wins():
    psb = [_promo("ПСБ", "Карты", CASHBACK, 30.0, "%")]
    sber = [_promo("Сбер", "Карты", CASHBACK, 10.0, "%")]
    result = compare_segments(psb, sber)[0]
    assert result.verdict == "red"
    assert "30 %" in result.headline


def test_equal_benefit_is_parity():
    psb = [_promo("ПСБ", "Карты", CASHBACK, 10.0, "%")]
    sber = [_promo("Сбер", "Карты", CASHBACK, 10.0, "%")]
    assert compare_segments(psb, sber)[0].verdict == "yellow"


def test_lower_credit_rate_wins():
    psb = [_promo("ПСБ", "Кредиты", RATE, 5.0, "%")]
    sber = [_promo("Сбер", "Кредиты", RATE, 3.0, "%")]
    assert compare_segments(psb, sber)[0].verdict == "green"


def test_deposit_rate_inverted():
    psb = [_promo("ПСБ", "Вклады", RATE, 13.0, "%")]
    sber = [_promo("Сбер", "Вклады", RATE, 14.0, "%")]
    assert compare_segments(psb, sber)[0].verdict == "green"


def test_different_units_not_compared():
    """«Кешбэк 30%» и «кешбэк 9000 ₽» — величины разной природы."""
    psb = [_promo("ПСБ", "Карты", CASHBACK, 30.0, "%")]
    sber = [_promo("Сбер", "Карты", CASHBACK, 9000.0, "₽")]
    result = compare_segments(psb, sber)[0]
    assert result.verdict == "grey"
    assert "несопоставим" in result.headline


def test_prize_excluded_from_comparison():
    """Розыгрыш достаётся одному человеку — это не выгода всем клиентам."""
    psb = [_promo("ПСБ", "Карты", PRIZE, 1_000_000.0, "₽"),
           _promo("ПСБ", "Карты", CASHBACK, 5.0, "%")]
    sber = [_promo("Сбер", "Карты", CASHBACK, 10.0, "%")]
    result = compare_segments(psb, sber)[0]
    assert result.verdict == "green"
    assert result.psb_best == 5.0


def test_prizes_sort_last():
    prize = _promo("ПСБ", "Карты", PRIZE, 1_000_000.0, "₽", "Розыгрыш")
    cashback = _promo("ПСБ", "Карты", CASHBACK, 5.0, "%", "Кешбэк")
    assert sorted([prize, cashback], key=sort_key)[0].title == "Кешбэк"


def test_segment_without_sber_is_red():
    psb = [_promo("ПСБ", "Карты", CASHBACK, 30.0, "%")]
    result = compare_segments(psb, [])[0]
    assert result.verdict == "red"
    assert "нет ни одного" in result.headline


def test_classify_rejects_article():
    assert classify("ПСБ", "Что такое акции", "", "", "/personal/wealth/x") is None


# --- выбор витринного предложения ----------------------------------------

def test_best_offer_prefers_percent_over_points():
    """«2000 баллов» не сильнее «кешбэка 30%»: 2000 больше 30 лишь на вид."""
    from src.promos import best_offer

    promos = [
        _promo("ПСБ", "Карты", POINTS, 2000.0, "баллов", "2000 баллов"),
        _promo("ПСБ", "Карты", CASHBACK, 30.0, "%", "Кешбэк 30%"),
    ]
    assert best_offer(promos).title == "Кешбэк 30%"


def test_best_offer_follows_segment_unit():
    """Витрина показывает ту же величину, по которой вынесен вердикт."""
    from src.promos import best_offer

    promos = [
        _promo("ПСБ", "Карты", CASHBACK, 30.0, "%", "Кешбэк 30%"),
        _promo("ПСБ", "Карты", CASHBACK, 9000.0, "₽", "Кешбэк 9000 ₽"),
    ]
    assert best_offer(promos, CASHBACK, "₽").title == "Кешбэк 9000 ₽"


def test_best_offer_skips_prizes():
    from src.promos import best_offer

    promos = [
        _promo("ПСБ", "Карты", PRIZE, 1_000_000.0, "₽", "Розыгрыш"),
        _promo("ПСБ", "Карты", CASHBACK, 5.0, "%", "Кешбэк 5%"),
    ]
    assert best_offer(promos).title == "Кешбэк 5%"


def test_partner_name_does_not_make_it_a_service():
    """«Домашний кешбэк» от компании «Правокард» — это кешбэк, а не услуга."""
    segment = segment_of(
        "/personal/domashniy-cashback",
        "Домашний кешбэк",
        "Сертификат на возмещение до 60% за стройматериалы от Компании «Правокард»",
        benefit_type=CASHBACK,
    )
    assert segment == BONUS_SEGMENT


def test_service_detected_from_title():
    assert segment_of("/personal/x", "Бесплатные консультации") == "Сервисы и услуги"


# --- формулировки ---------------------------------------------------------

@pytest.mark.parametrize("count,expected", [
    (1, "1 предложение"), (2, "2 предложения"), (4, "4 предложения"),
    (5, "5 предложений"), (11, "11 предложений"), (14, "14 предложений"),
    (21, "21 предложение"), (22, "22 предложения"), (25, "25 предложений"),
    (101, "101 предложение"), (0, "0 предложений"),
])
def test_offers_count_agrees_with_number(count, expected):
    from src.promos import offers_count

    assert offers_count(count) == expected


def test_benefit_phrase_agrees_in_gender():
    """«Максимальный ставка» — рассогласование, которое видно в отчёте."""
    from src.promos import benefit_phrase

    assert benefit_phrase(CASHBACK) == "максимальный кешбэк"
    assert benefit_phrase(RATE, lower_is_better=True) == "минимальная ставка"
    assert benefit_phrase(RATE, lower_is_better=False) == "максимальная ставка"


def test_credit_rate_headline_says_minimal():
    """По кредиту выгодна ставка ниже — в выводе должно стоять «минимальная»."""
    psb = [_promo("ПСБ", "Кредиты", RATE, 5.0, "%")]
    sber = [_promo("Сбер", "Кредиты", RATE, 17.9, "%")]
    result = compare_segments(psb, sber)[0]
    assert result.headline.startswith("Минимальная ставка")
    assert result.verdict == "red"


def test_deposit_rate_headline_says_maximal():
    psb = [_promo("ПСБ", "Вклады", RATE, 13.0, "%")]
    sber = [_promo("Сбер", "Вклады", RATE, 14.0, "%")]
    result = compare_segments(psb, sber)[0]
    assert result.headline.startswith("Максимальная ставка")
    assert result.verdict == "green"


@pytest.mark.parametrize("title,expected", [
    ("Получите до 2000 баллов", 2000.0),
    # Между числом и «баллов» почти всегда стоит определение.
    ("Получите до 4000 бонусных баллов за перевод пенсии", 4000.0),
    ("2000 приветственных баллов", 2000.0),
])
def test_points_with_adjective(title, expected):
    benefit_type, value, unit = parse_benefit(title)
    assert (benefit_type, value, unit) == (POINTS, expected, "баллов")
