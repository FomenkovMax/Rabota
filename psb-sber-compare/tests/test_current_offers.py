from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src import availability, current_offers
from src.report import _current_offers_block
from src.promos import classify_all
from src.psb.parser import Product, Promo
from src.storage import Storage


NOW = datetime(2026, 11, 19, 12, tzinfo=current_offers.MOSCOW)
SOURCE = "https://bank.example/offer"
LNR = availability.Status(availability.LNR, "условия в ЛНР", SOURCE)
CITY = availability.Status(availability.LNR, "есть подтверждение услуги в Луганске: Луганск", SOURCE)


def deposit(bank, rate, status, *, hours=1):
    product = Product(
        bank=bank, title=f"Вклад {bank}", category="Вклады", source_url=SOURCE,
        collected_at=(NOW - timedelta(hours=hours)).isoformat(),
        rate_min=rate, rate_max=rate, rate_raw=f"{rate}%",
        amount_min=10_000, amount_max=1_000_000,
        term_min_months=12, term_max_months=12,
        terms={"Валюта": "Рубли", "Выплата процентов": "В конце срока",
               "База начисления процентов": "Год"},
    )
    return product, status


@pytest.mark.parametrize(("region", "expected"), [
    ("lnr", [("А", 60_000), ("Б", 50_000)]),
    ("lugansk", [("Б", 50_000)]),
])
def test_rankings_only_include_fresh_exact_regional_scenarios(region, expected):
    pairs = [deposit("А", 12, LNR), deposit("Б", 10, CITY),
             deposit("В", 20, CITY, hours=73), deposit("Г", 25, CITY)]
    pairs[-1][0].rate_raw = "до 25%"
    products, statuses = zip(*pairs)
    ranking = current_offers.rankings(
        products, dict(zip(map(id, products), statuses)), ["А", "Б", "В", "Г", "Д"],
        region=region, now=NOW, hours=72, key_rate=None,
        region_methods=dict.fromkeys(("А", "Б", "В", "Г", "Д"), "selector"),
    )["Вклады"]
    assert [(leader.bank, leader.value) for leader in ranking["leaders"]] == expected
    assert ranking["checked"] == len(expected)
    assert ranking["total"] == 5
    assert "Д" in ranking["excluded_banks"]


def test_credit_metric_requires_exact_psk_and_known_fees():
    product = Product(category="Кредиты", title="Кредит наличными", apr_min=20, apr_max=20,
                      apr_raw="20 %", amount_min=10_000, amount_max=900_000,
                      term_min_months=36, term_max_months=36,
                      terms={"Обязательные платные услуги": "Нет"})
    assert current_offers._scenario_metric(product, 36) == 20
    product.apr_max = 26
    assert current_offers._scenario_metric(product, 36) is None
    product.apr_max = 20
    product.terms.clear()
    assert current_offers._scenario_metric(product, 36) is None


def promo_with(period, *, territory="Луганске", hours=1):
    return Promo("Акция с кешбэком", source_url=SOURCE,
                 checked_at=(NOW - timedelta(hours=hours)).isoformat(),
                 text=f"{period}. Акция действует в {territory}. Условия участия: оплатите три покупки картой.")


@pytest.mark.parametrize(("period", "territory", "hours", "lnr", "city"), [
    ("Акция действует с 01.11.2026 по 19.11.2026", "Луганске", 24, True, True),
    ("Акция действует до 19.11.2026", "Луганске", 1, False, False),
    ("Акция проводится с 20.11.2026 по 30.11.2026", "Луганске", 1, False, False),
    ("Акция действует по 18.11.2026", "Луганске", 1, False, False),
    ("Акция действует до отмены", "ЛНР", 1, True, False),
    ("Акция действует бессрочно", "Луганске", 25, False, False),
    ("Успейте оформить карту до 30.11.2026", "Луганске", 1, False, False),
    ("Акция действует по 30.11.2026", "России", 1, False, False),
    ("Кешбэк 5%", "Луганске", 1, False, False),
])
def test_promo_needs_current_source_term_conditions_and_geography(period, territory, hours, lnr, city):
    promo, = classify_all([promo_with(period, territory=territory, hours=hours)],
                          "Банк", today=NOW.date())
    for region, expected in (("lnr", lnr), ("lugansk", city)):
        assert current_offers.active_promo(promo, region=region, now=NOW, hours=24) == expected


def test_copy_keeps_source_dates_and_missing_old_promo_date(tmp_path):
    storage = Storage(tmp_path / "banks.db")
    try:
        original = storage.start_run("ЛНР")
        latest = storage.start_run("ЛНР")
        older = promo_with("Акция действует до отмены", hours=25)
        legacy = SimpleNamespace(key=lambda: "legacy", title="Акция с кешбэком",
                                 text=older.text, url=SOURCE, source_path="")
        storage.save_promos(original, "Банк", [older, legacy])
        storage.copy_bank_promos(original, latest, "Банк")
        promos = classify_all(storage.promos_of_run(latest), "Банк", today=NOW.date())
        assert [promo.checked_at for promo in promos] == [older.checked_at, ""]
        assert all(not current_offers.active_promo(p, region="lnr", now=NOW, hours=24) for p in promos)
    finally:
        storage.close()


def test_promo_terms_link_without_participation_conditions_is_not_enough():
    promo = promo_with("Акция действует до отмены")
    promo.text = promo.text.replace("оплатите три покупки картой", "условия доступны по ссылке")
    insight, = classify_all([promo], "Банк", today=NOW.date())
    assert not current_offers.active_promo(insight, region="lnr", now=NOW, hours=24)


def test_main_offer_table_shows_only_comparable_confirmed_offers():
    verified, status = deposit("ВТБ", 11, CITY)
    salary, other = deposit("Сбер", 14.5, CITY)
    salary.title = "Зарплатный Максимум"
    missing, outside = deposit("Банк без подтверждения в городе", 15, LNR)
    rows = [verified, salary, missing]
    ranks = current_offers.rankings(
        rows, dict(zip(map(id, rows), (status, other, outside))),
        [product.bank for product in rows], region="lugansk", now=NOW,
        hours=72, key_rate=None,
        region_methods=dict.fromkeys((p.bank for p in rows), "selector"),
    )
    markup = _current_offers_block({"lugansk": {"rankings": ranks, "promos": []}})
    assert "Вклад ВТБ" in markup
    assert "55 000,00 ₽ до налога" in markup
    assert "Зарплатный Максимум" not in markup
    assert "Банк без подтверждения в городе" not in markup
    assert "Сопоставимые условия у 1 из 3 банков" in markup
