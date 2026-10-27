"""Расчёты проверяются независимыми ручными вычислениями; продукты — из фрагментов реальных страниц."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from bankintel.analytics.calc import simple_interest
from bankintel.analytics.compare import DEFAULT_SCENARIOS, Scenario, compare, evaluate
from bankintel.analytics.facts import facts_from_params
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchedDocument, SourceRef
from bankintel.sources.common import index_conditions

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def test_simple_interest_exact():
    assert simple_interest(D(100_000), D(12), 365) == D("12000.00")
    assert simple_interest(D(100_000), D(15), 91) == D("3739.73")  # 15000*91/365 = 3739.726...
    assert simple_interest(D(500_000), D("14.1"), 365) == D("70500.00")
    assert simple_interest(D("0.01"), D(10), 1) == D("0.00")
    assert isinstance(simple_interest(D(1), D(1), 1), D)


def test_simple_interest_rejects_negative():
    with pytest.raises(ValueError):
        simple_interest(D(-1), D(1), 1)


def test_scenario_days():
    assert [Scenario(D(1), m).days for m in (3, 6, 12)] == [91, 183, 365]
    with pytest.raises(ValueError):
        Scenario(D(0), 3)


def _psb_facts():
    adapter = get_adapter("psb")("psb")
    src = SourceRef("deposits", "https://www.psbank.ru/personal/saving", "deposit")
    cards = adapter.parse(src, FetchedDocument(src.url, (FIX / "psb_deposits_cards.html").read_bytes()))
    detail_ref = SourceRef("detail:1", "https://www.psbank.ru/personal/saving/myincome", "deposit")
    rows = adapter.parse_detail(detail_ref, FetchedDocument(detail_ref.url, (FIX / "psb_detail_table.html").read_bytes()))
    detail = {"conditions": index_conditions(rows)}
    out = []
    for p in cards:
        out.append(facts_from_params(
            bank={"slug": "psb", "name": "ПСБ", "is_benchmark": False},
            product={"name": p.name, "category": p.category.value}, card=p.params,
            conditions=detail if p.name == "Мой доход" else None,
        ))
    return out


def _card(name):
    adapter = get_adapter("psb")("psb")
    src = SourceRef("deposits", "https://www.psbank.ru/personal/saving", "deposit")
    return next(p.params for p in adapter.parse(src, FetchedDocument(src.url, (FIX / "psb_deposits_cards.html").read_bytes())) if p.name == name)


def _vtb_facts():
    adapter = get_adapter("vtb")("vtb")
    src = SourceRef("deposits", "https://www.vtb.ru/personal/vklady-i-scheta/", "deposit")
    cards = adapter.parse(src, FetchedDocument(src.url, (FIX / "vtb_cards.html").read_bytes()))
    return [facts_from_params(bank={"slug": "vtb", "name": "ВТБ", "is_benchmark": False},
                              product={"name": p.name, "category": p.category.value}, card=p.params) for p in cards]


def by(facts):
    return {f.name: f for f in facts}


def test_real_fixtures_to_facts():
    psb = by(_psb_facts())
    f = psb["Мой доход"]
    assert (f.rate_min, f.rate_max, f.currency) == (D("12.00"), D("14.10"), "RUB")
    assert f.term_text == "91 – 731 дней" and f.term.allows(365)  # срок взят со страницы продукта
    assert f.amount.min == D(50000)
    assert psb["Народный вклад"].amount.max == D(150000)
    assert psb["В юанях"].currency == "CNY"
    vtb = by(_vtb_facts())
    assert "floating_rate" in vtb["Ключевой"].flags
    assert "restricted_audience" in vtb["Социальный вклад"].flags
    assert "restricted_audience" in vtb["Инвестиционный+"].flags      # ставка только при вложении в паи фондов
    drag = facts_from_params(  # описание — дословно с сайта ПСБ
        bank={"slug": "psb", "name": "ПСБ"}, product={"name": "Драгоценный", "category": "deposit"},
        card={"title": "Вклад «Драгоценный»", "description": "Купите драгоценные металлы и откройте вклад на специальных условиях"},
    )
    assert "restricted_audience" in drag.flags                        # нужна покупка драгметаллов
    assert "restricted_audience" not in vtb["Вместе"].flags


def test_evaluate_interval_income_and_warnings():
    r = evaluate(by(_psb_facts())["Мой доход"], Scenario(D(500_000), 12), NOW)
    assert r.eligible
    assert r.income_min == D("60000.00") and r.income_max == D("70500.00")  # 12% и 14,1% от 500 000 за 365 дн.
    assert any("зависит от срока, суммы" in w for w in r.warnings)
    assert any("ЛНР не подтверждена" in w for w in r.warnings)


def test_exclusions_have_reasons():
    psb = by(_psb_facts())
    assert "сумма больше максимальной" in evaluate(psb["Народный вклад"], Scenario(D(500_000), 3), NOW).exclusion
    assert "валюта CNY" in evaluate(psb["В юанях"], Scenario(D(100_000), 12), NOW).exclusion
    no_term = facts_from_params(bank={"slug": "psb", "name": "ПСБ"}, product={"name": "Мой доход", "category": "deposit"},
                                card=_card("Мой доход"))  # на карточке срока нет, страница продукта не загружена
    assert "срок на сайте не указан" in evaluate(no_term, Scenario(D(100_000), 12), NOW).exclusion
    assert evaluate(psb["Стабильный доход"], Scenario(D(100_000), 12), NOW).eligible
    vtb = by(_vtb_facts())
    assert "сумма меньше минимальной" in evaluate(vtb["Выгодное начало"], Scenario(D(5_000), 3), NOW).exclusion
    assert "срок на сайте не указан" in evaluate(vtb["Ключевой"], Scenario(D(1_000_000), 12), NOW).exclusion  # срока нет на карточке ВТБ
    assert "не подходит" in evaluate(vtb["Выгодное начало"], Scenario(D(100_000), 12), NOW).exclusion  # только 3 мес.


def test_upper_bound_only_when_min_rate_missing():
    r = evaluate(by(_vtb_facts())["Двойная выгода"], Scenario(D(100_000), 6), NOW)
    assert r.eligible and r.income_min is None and r.income_max == simple_interest(D(100_000), D(18), 183)
    assert any("нижняя граница" in w for w in r.warnings)


def test_compare_ranks_and_reports_missing_banks():
    facts = _psb_facts() + _vtb_facts()
    rep = compare(facts, Scenario(D(100_000), 3), all_banks=[("sber", "Сбербанк"), ("psb", "ПСБ"), ("vtb", "ВТБ")], now=NOW)
    assert rep.banks_without_data == ["Сбербанк"]
    incomes = [r.income_max for r in rep.eligible]
    assert incomes == sorted(incomes, reverse=True)
    best = rep.best_by_bank()
    assert set(best) <= {"psb", "vtb"}
    assert all("restricted_audience" not in r.facts.flags for r in best.values())  # условные предложения не в основном рейтинге
    assert best["vtb"].facts.name == "Вместе"
    restricted = rep.best_by_bank(restricted=True)
    assert restricted["vtb"].facts.name in {"Инвестиционный+", "Двойная выгода", "Выгодное начало"}
    assert all(not r.facts.category != "deposit" for r in rep.results)  # счета в расчёт не входят


def test_stale_data_warning():
    f = by(_vtb_facts())["Выгодное начало"]
    f.checked_at = NOW - timedelta(days=10)
    r = evaluate(f, Scenario(D(100_000), 3), NOW)
    assert any("старше 7 дней" in w for w in r.warnings)
    f.checked_at = None
    assert any("дата проверки неизвестна" in w for w in evaluate(f, Scenario(D(100_000), 3), NOW).warnings)


def test_default_scenarios_run_without_errors():
    facts = _psb_facts() + _vtb_facts()
    for sc in DEFAULT_SCENARIOS:
        rep = compare(facts, sc, now=NOW)
        assert len(rep.results) == len([f for f in facts if f.category == "deposit"])


def test_term_conflict_prefers_stricter_value_and_records_note():
    card = {"title": "Т", "term_text": "91, 181 и 367 дней", "headline_rate_pct": {"min": "13", "max": "14"}, "currency": "RUB"}
    f = facts_from_params(bank={"slug": "b", "name": "Б"}, product={"name": "Т", "category": "deposit"}, card=card,
                          conditions={"conditions": {"term": "91–367 дней"}})
    assert f.term.values == (91, 181, 367) and f.notes and "расходятся" not in f.notes[0] and "вариант карточки" in f.notes[0]
    assert not f.term.allows(270)  # диапазон страницы разрешил бы 270 дней — карточка не разрешает


def test_limited_time_flag_from_real_description():
    # описание дословно с сайта ПСБ (24.10.2026)
    d = "Станьте клиентом банка за несколько минут и откройте вклад онлайн до 14 декабря, чтобы поддержать социальный проект"
    f = facts_from_params(bank={"slug": "psb", "name": "ПСБ"}, product={"name": "Вклад в Победу", "category": "deposit"},
                          card={"title": "Вклад «Вклад в Победу»", "description": d})
    assert "limited_time" in f.flags and "restricted_audience" not in f.flags


def test_exclusion_wording_for_unparsed_vs_missing_term():
    unparsed = facts_from_params(bank={"slug": "psb", "name": "ПСБ"}, product={"name": "X", "category": "deposit"},
                                 card={**_card("Мой доход"), "term_text": "уточняйте у менеджера"})
    reason = evaluate(unparsed, Scenario(D(100_000), 12), NOW).exclusion
    assert reason == "срок «уточняйте у менеджера» не распознан"
    missing = facts_from_params(bank={"slug": "psb", "name": "ПСБ"}, product={"name": "Y", "category": "deposit"}, card=_card("Мой доход"))
    assert evaluate(missing, Scenario(D(100_000), 12), NOW).exclusion == "срок на сайте не указан"
