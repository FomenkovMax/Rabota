"""Адаптер ЦМРБанка. Страницы и эталон — настоящие данные сайта (24.10.2026); эталон снят Playwright с настоящего калькулятора."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bankintel.analytics.rate_tables import lookup, max_rate, nearest_fixed_term
from bankintel.domain.enums import AvailabilityStatus, ProductCategory
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchedDocument, SourceRef
from bankintel.sources.cmr import build_rate_table, extract_js_object
from bankintel.sources.common import ParseError

FIX = Path(__file__).parent / "fixtures"
GOLDEN = json.loads((FIX / "cmr_calculator_golden.json").read_text(encoding="utf-8"))
DEP = SourceRef("deposits", "https://www.cmrbank.ru/person/person-deposit/deposit-calc/", "deposit")
ACC = SourceRef("savings_accounts", "https://www.cmrbank.ru/person/person-deposit/deposit-account/", "savings")


def parse(src, fixture):
    return get_adapter("cmr")("cmr").parse(src, FetchedDocument(src.url, (FIX / fixture).read_bytes()))


@pytest.fixture(scope="module")
def deposits():
    return {p.params["source_id"]: p for p in parse(DEP, "cmr_deposit_calc.html")}


@pytest.fixture(scope="module")
def accounts():
    return parse(ACC, "cmr_deposit_account.html")


# ---------- извлечение JSON ----------

def test_extract_js_object_handles_braces_and_quotes_inside_strings():
    html = r'''var x = {deposites: {"1": {"name": "Вклад \"A}\" {x", "n": [1, {"b": "}"}]}, "2": {}}, other: 5}'''
    assert extract_js_object(html, "deposites") == {"1": {"name": 'Вклад "A}" {x', "n": [1, {"b": "}"}]}, "2": {}}


@pytest.mark.parametrize("html", ["<html>нет данных</html>", "deposites: нет объекта", 'deposites: {"a": 1', 'deposites: {"a": }'])
def test_extract_js_object_errors_are_parse_errors(html):
    with pytest.raises(ParseError):
        extract_js_object(html, "deposites")


def test_layout_change_is_parse_error_not_empty_result():
    adapter = get_adapter("cmr")("cmr")
    with pytest.raises(ParseError):
        adapter.parse(DEP, FetchedDocument(DEP.url, b"<html>new layout</html>"))
    root = SourceRef("site_root", "https://www.cmrbank.ru", "discovery")
    assert adapter.parse(root, FetchedDocument(root.url, b"<html/>")) == []


# ---------- каталожные значения против страницы банка ----------

def test_catalog_matches_what_the_bank_calculator_shows(deposits, accounts):
    meta = {m["id"]: m for m in GOLDEN["pages"]["deposits"]["meta"]}
    assert set(deposits) == set(meta)
    for pid, p in deposits.items():
        m = meta[pid]
        assert Decimal(p.params["headline_rate_pct"]["max"]) == Decimal(str(m["max_rate"])), p.name   # «До X %» — как у калькулятора
        assert p.params["has_replenish"] == m["has_replenish"] and p.params["has_withdraw"] == m["has_withdraw"]
        assert p.params["rate_table"]["min_term"] == m["min_term"] and p.params["rate_table"]["max_term"] == m["max_term"]
        assert p.params["rate_table"]["fixed_terms"] == m["fixed"]
        assert p.category == ProductCategory.DEPOSIT and p.lnr_status == AvailabilityStatus.NOT_CONFIRMED and p.lnr_quote is None
    (acc,) = accounts
    am = GOLDEN["pages"]["accounts"]["meta"][0]
    assert acc.category == ProductCategory.SAVINGS and Decimal(acc.params["headline_rate_pct"]["max"]) == Decimal(str(am["max_rate"]))


def test_product_names_flags_and_sources(deposits, accounts):
    names = {p.name for p in deposits.values()}
    assert names == {"Доход на максимум", "Доход на максимум для пенсионеров", "Доход на максимум+", "ЦМР Резерв", "ЦМР Старт"}  # пенсионный — отдельный продукт
    assert deposits["34"].params["floating_rate"] is True and deposits["21"].params["floating_rate"] is False   # переменная ставка — по примечанию на странице
    meta = {m["id"]: m for m in GOLDEN["pages"]["deposits"]["meta"]}
    assert deposits["35"].params["headline_rate_text"] == "До 15 %"
    assert deposits["35"].params["amount_text"] == "От 30 000 руб." and meta["35"]["min_sum"] == 30_000      # значение — из эталона, не из памяти
    for pid, p in deposits.items():
        assert p.params["amount_text"] == f"От {meta[pid]['min_sum']:,} руб.".replace(",", " ")
    assert deposits["21"].params["conditions_pdf"].startswith("https://www.cmrbank.ru/files/deposit/cmr_rus/")
    assert accounts[0].name == "Больше чем счет" and accounts[0].params["floating_rate"] is False


# ---------- порт калькулятора против настоящего калькулятора (Playwright) ----------

PAYOUT = {"at_end": "at_end", "at_month_deposit": "monthly", "at_month_account": "monthly"}


def test_rate_lookup_matches_bank_calculator_on_every_golden_point(deposits):
    checked = mismatches = enabled = 0
    problems = []
    for pid, points in GOLDEN["pages"]["deposits"]["results"].items():
        table = deposits[pid].params["rate_table"]
        for key, expected in points.items():
            amount, term, pay, rep, wd = key.split("|")
            quote = lookup(table, Decimal(amount), int(term), PAYOUT[pay], need_replenish=rep == "1", need_withdraw=wd == "1")
            checked += 1
            if expected is None:
                got_ok = quote is None
            else:
                enabled += 1
                got_ok = (quote is not None and quote.rate == Decimal(str(expected[0])) and quote.term_days == expected[1]
                          and int(quote.replenish) == expected[2] and int(quote.withdraw) == expected[3])
            if not got_ok:
                mismatches += 1
                problems.append((pid, key, expected, quote))
    assert checked == 5670 and enabled > 900          # сетка полностью прогнана, и ставки в ней не пустые
    assert mismatches == 0, f"расхождений с калькулятором банка: {mismatches}; первые: {problems[:5]}"


def test_golden_actually_contains_all_kinds_of_behaviour():
    """Эталон не должен быть тривиальным: есть и «нет ставки», и разные сроки, и ограничения по пополнению/снятию."""
    pts = [v for r in GOLDEN["pages"]["deposits"]["results"].values() for v in r.values()]
    assert any(v is None for v in pts) and any(v for v in pts)
    assert {v[1] for v in pts if v} >= {31, 91, 181, 276, 367}
    assert {(v[2], v[3]) for v in pts if v} >= {(0, 0), (1, 1)}


def test_known_values_from_the_live_calculator_screen(deposits):
    """Значения, увиденные на странице калькулятора после загрузки (300 000 ₽, 31 день, выплата в конце срока)."""
    q = lookup(deposits["35"].params["rate_table"], 300_000, 31)
    assert q.rate == Decimal("15.0") and q.term_days == 31
    assert lookup(deposits["30"].params["rate_table"], 300_000, 31).rate == Decimal("12.7")
    assert lookup(deposits["21"].params["rate_table"], 300_000, 31).rate == Decimal("12.5")
    assert lookup(deposits["30"].params["rate_table"], 49_999, 31) is None   # ниже минимальной суммы вклада (50 000)


def test_fixed_term_rounding_and_tolerance(deposits):
    table = deposits["21"].params["rate_table"]
    assert nearest_fixed_term(table, 365) == 367 and nearest_fixed_term(table, 91) == 91 and nearest_fixed_term(table, 200) is None
    assert lookup(table, 300_000, 300).term_days == 276        # как у калькулятора банка: срок «между» -> ближайший меньший
    assert lookup(table, 300_000, 5000) is None and lookup(table, 300_000, 10) is None


def test_max_rate_and_table_shape(deposits):
    for pid, p in deposits.items():
        t = p.params["rate_table"]
        assert max_rate(t) == Decimal(p.params["headline_rate_pct"]["max"])
        assert t["tiers"] and all(isinstance(x["min_sum"], int | float) for x in t["tiers"])


def test_rate_values_are_exact_strings_not_floats(deposits):
    raw = json.dumps(deposits["21"].params["rate_table"])
    assert "12.5" in raw and "0.30000000000000004" not in raw
    t = build_rate_table({"name": "x", "max_term": 0, "sums": {"1": 100}, "terms": {"7": 31}, "rates": {"1": {
        "replenish": None, "withdraw": None, "salary_card": False,
        "pct_at_and": {"salary_card_disable": [None] * 7 + [9.1]}, "pct_at_month": {"salary_card_disable": {"7": ""}}}}})
    assert t["tiers"][0]["terms"][0] == {"id": "7", "days": 31, "at_end": "9.1", "monthly": None}   # список и словарь, '' и null — «нет ставки»


# ---------- интеграция: факты, сценарии, БД, бот ----------

from datetime import UTC, datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402

from bankintel.analytics.calc import simple_interest  # noqa: E402
from bankintel.analytics.compare import Scenario, compare, evaluate  # noqa: E402
from bankintel.analytics.facts import facts_from_params  # noqa: E402
from bankintel.bot import compare_views  # noqa: E402
from bankintel.collector import collect_bank  # noqa: E402
from bankintel.db.models import Bank  # noqa: E402
from bankintel.details import collect_details  # noqa: E402
from bankintel.domain.enums import FetchOutcome  # noqa: E402
from bankintel.sources.base import FetchDiagnostic  # noqa: E402

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def facts_of(ep):
    f = facts_from_params(bank={"slug": "cmr", "name": "ЦМР банк"}, product={"name": ep.name, "category": ep.category.value}, card=ep.params)
    f.checked_at, f.document_ids = NOW, [1]
    return f


@pytest.fixture(scope="module")
def facts(deposits, accounts):
    return {p.name: facts_of(p) for p in [*deposits.values(), *accounts]}


def golden_rate(pid, amount, term, pay="at_end"):
    v = GOLDEN["pages"]["deposits"]["results"][pid][f"{amount}|{term}|{pay}|0|0"]
    return Decimal(str(v[0])) if v else None


def test_scenario_uses_exact_bank_rate_not_a_range(facts):
    r = evaluate(facts["Доход на максимум"], Scenario(Decimal(300_000), 6), NOW)        # 6 мес. = 183 дн. -> срок банка 181
    assert r.eligible and r.rate == golden_rate("21", 300000, 181) and r.income_min == r.income_max
    assert r.income_max == simple_interest(Decimal(300_000), r.rate, 183)
    assert any("точная ставка" in w for w in r.warnings) and any("срок продукта 181" in w for w in r.warnings)
    r12 = evaluate(facts["Доход на максимум"], Scenario(Decimal(500_000), 12), NOW)     # 365 -> 367
    assert r12.rate == golden_rate("21", 500000, 367)


def test_each_golden_scenario_rate_comes_from_the_bank_table(facts):
    for name, pid in (("Доход на максимум", "21"), ("Доход на максимум+", "30"), ("ЦМР Резерв", "34")):
        for amount, months, term in ((100_000, 3, 91), (500_000, 6, 181), (1_000_000, 12, 367)):
            r = evaluate(facts[name], Scenario(Decimal(amount), months), NOW)
            expected = golden_rate(pid, amount, term)
            if expected is None or (name == "Доход на максимум" and amount > 500_000):
                assert not r.eligible
            else:
                assert r.eligible and r.rate == expected, (name, amount, months)


def test_exclusions_have_reasons(facts):
    assert "не подходит под сроки" in evaluate(facts["ЦМР Старт"], Scenario(Decimal(300_000), 3), NOW).exclusion   # только 31 день
    assert "сумма меньше минимальной" in evaluate(facts["ЦМР Старт"], Scenario(Decimal(10_000), 1), NOW).exclusion
    assert "сумма больше максимальной" in evaluate(facts["Доход на максимум"], Scenario(Decimal(1_000_000), 12), NOW).exclusion   # поле max_sum
    assert "не подходит" in evaluate(facts["Доход на максимум"], Scenario(Decimal(300_000), 5), NOW).exclusion     # 152 дн.: нет такого срока
    one_month = evaluate(facts["ЦМР Старт"], Scenario(Decimal(300_000), 1), NOW)         # 1 мес. = 30 дн., у банка 31
    assert one_month.eligible and one_month.rate == Decimal("15.0")


def test_flags(facts):
    assert "floating_rate" in facts["ЦМР Резерв"].flags and "floating_rate" not in facts["Доход на максимум"].flags
    assert "restricted_audience" in facts["Доход на максимум для пенсионеров"].flags      # для пенсионеров
    assert "restricted_audience" in facts["ЦМР Старт"].flags                             # для новых клиентов с картой
    assert "restricted_audience" not in facts["Доход на максимум"].flags
    assert facts["Больше чем счет"].category == "savings" and facts["Доход на максимум"].lnr_status == "unknown"


def test_catalog_term_and_amount_come_from_the_table(facts):
    f = facts["Доход на максимум"]
    assert f.term.values and 367 in f.term.values and f.amount.min == Decimal(10_000) and f.amount.max == Decimal(500_000)
    assert any("max_sum" in n for n in f.notes)
    assert facts["ЦМР Старт"].term_text == "31 дн."


class _Pages:
    async def fetch(self, source):
        name = "cmr_deposit_calc.html" if source.key == "deposits" else "cmr_deposit_account.html"
        return FetchedDocument(source.url, (FIX / name).read_bytes(), "text/html"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


async def test_end_to_end_through_database_and_bot(seeded, tmp_path):
    async with seeded() as s:
        cmr = await s.scalar(select(Bank).where(Bank.slug == "cmr"))
        run = await collect_bank(s, cmr, _Pages(), tmp_path)
        assert run.status == "ok"
        det = await collect_details(s, cmr, _Pages(), tmp_path)
        assert det.status == "ok" and "нет отдельных страниц" in det.message      # у ЦМР нет страниц продуктов — это не сбой
        from bankintel.analytics.facts import load_facts

        loaded = {f.name: f for f in await load_facts(s)}
        assert {"Доход на максимум", "ЦМР Старт", "Больше чем счет"} <= set(loaded) and loaded["Доход на максимум"].rate_table
        text = await compare_views.compare_for_bot(s, Scenario(Decimal(300_000), 6))
        assert "ЦМР банк" in text and "точная" in text
        assert "ЦМР банк</b> — данных нет" not in text
        cat = compare_views.deposits_text(list(loaded.values()))
        assert "Доход на максимум" in cat and "до 13,1%" in cat   # каталог показывает «до X%», как на сайте банка


def test_compare_report_prints_single_value_for_exact_rate(facts):
    rep = compare(list(facts.values()), Scenario(Decimal(300_000), 6), now=NOW)
    line = compare_views._line(next(r for r in rep.eligible_open if r.facts.name == "Доход на максимум"))
    assert "точная" in line and " – " not in line


def test_informational_notes_are_not_reported_as_source_conflicts(facts):
    f = facts["Доход на максимум"]
    assert f.notes and "sources_conflict" not in f.flags      # примечание про max_sum — справка, а не расхождение источников
