"""Обзор отчёта: выводы и графики строятся из тех же данных, что таблицы."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import charts, market


def _gap(program, block, better, sber, others, status, rank):
    offers = [market.Offer("Сбер", sber, program, "")] + [
        market.Offer(b, v, program, "") for b, v in others.items()]
    g = market.Gap(block=block, program=program, metric="rate_max" if better == "higher"
                   else "rate_min", better=better, category=program)
    g.offers, g.sber, g.status, g.rank, g.banks_compared = offers, offers[0], status, rank, len(offers)
    best = max(offers, key=lambda o: o.value) if better == "higher" else min(offers, key=lambda o: o.value)
    g.best = best
    rest = sorted(v for v in others.values())
    g.others_median = rest[len(rest) // 2]
    g.delta_vs_median = sber - g.others_median
    g.delta_vs_best = abs(sber - best.value)
    return g


GAPS = [
    _gap("Вклады", "DEP", "higher", 13.0, {"ВТБ": 14.2, "ПСБ": 13.8}, "отстаёт", 3),
    _gap("Потребительский кредит", "LOAN", "lower", 20.4, {"ПСБ": 19.9, "ВТБ": 21.0}, "в рынке", 2),
    _gap("Рефинансирование", "LOAN", "lower", 19.4, {"ПСБ": 19.9, "ВТБ": 20.5}, "лидер", 1),
]


def test_insights_name_the_worst_gap_with_numbers():
    text = " ".join(t for _, t in charts.insights(GAPS, home="Сбер"))
    assert "лидирует в 1, в рынке — 1, отстаёт в 1" in text
    assert "«Вклады»: до 13,00 % против до 14,20 % у ВТБ — разница 1,20 п.п." in text


def test_insights_use_genitive_and_quality_share():
    rows = [SimpleNamespace(bank="Сбер", rated=10, usable=7)]
    text = " ".join(t for _, t in charts.insights(GAPS, home="Сбер", quality_rows=rows))
    assert "Ставка Сбера найдена и проверена у 7 из 10 продуктов (70 %)" in text


def test_charts_render_from_gaps():
    assert "<svg" in charts.dumbbell(GAPS, home="Сбер")
    assert "ВТБ" in charts.bubbles(GAPS, home="Сбер")
    heat = charts.heatmap(GAPS, ["Сбер", "ПСБ", "ВТБ"], home="Сбер")
    assert "13,00 %" in heat and "−0,8" in heat
    assert "лидер" in charts.status_bars(GAPS, {"DEP": "Сбережения", "LOAN": "Кредиты"})


def test_empty_data_gives_no_chart():
    assert charts.dumbbell([], home="Сбер") == "" and charts.bubbles([], home="Сбер") == ""
    assert charts.funnel([], []) == ""


def test_calculator_takes_base_checked_rates_and_keeps_specials_as_pros():
    from src import conditions

    def p(bank, title, rate, terms=None):
        return SimpleNamespace(bank=bank, title=title, category="Кредиты", rate_min=rate,
                               rate_max=rate, apr_min=None, apr_max=None, amount_min=30_000,
                               amount_max=3_000_000, term_min_months=3, term_max_months=60,
                               terms=terms or {}, rate_conditions="", source_url="https://x",
                               region="ЛНР")
    salary = {conditions.TERMS_KEY: "для зарплатных клиентов: «получаю зарплату»"}
    offers = charts.calculator_offers(
        [p("Сбер", "Кредит наличными", 20.4), p("Сбер", "Кредит наличными зарплатным", 18.4, salary),
         p("ПСБ", "Кредит наличными", 19.9)],
        key_rate=14.0, region_methods={"Сбер": "selector", "ПСБ": "federal"})
    sber = next(o for o in offers if o["bank"] == "Сбер")
    assert sber["rate"] == 20.4 and "18,40 %" in sber["special"][0]
    html = charts.calculator_block(offers, home="Сбер")
    assert 'id="cSum"' in html and "Потребительский кредит" in html


def test_calculator_inputs_presets_and_table():
    offers = [{"program": "Новостройки", "kind": "Ипотека", "bank": "Сбер", "title": "Ипотека",
               "url": "u", "rate": 18.7, "apr": None, "sum": [None, None], "term": [None, None],
               "special": [], "calc": ""}]
    html = charts.calculator_block(offers, home="Сбер")
    for part in ('id="cSumIn"', 'id="cTermIn"', 'id="cSumChips"', 'id="cCap"', 'class="ctab"',
                 '"Ипотека": {"sum": [3000000'):
        assert part in html, part
    assert "</script>" in html and "__DATA__" not in html


def test_brand_logos_and_colors():
    from src import brand
    css = brand.css()
    for code in ("sber", "vtb", "psb", "tbank", "rostfinance", "cmr"):
        assert f".bl-{code}{{background-image:url(\"data:image/svg+xml;base64," in css, code
        assert f"--b-{code}:" in css
    assert brand.color("ВТБ") == "var(--b-vtb)"
    assert 'bl-other">Н</i>' in brand.name("Новый банк")      # неизвестный банк — буква
    assert "<script" not in brand.name("<script>")


def test_section_icons_are_added_once():
    from src import brand
    page = '<h2>Калькулятор: сколько это стоит</h2><details class="cat" open><summary>Ипотека<span>'
    out = brand.decorate(page)
    assert '<h2><i class="sic ic-calc"></i>Калькулятор' in out
    assert '<summary><i class="sic ic-mortgage"></i>Ипотека' in out
    assert brand.decorate(out) == out or out.count("ic-calc") == 1
    css = brand.icons_css()
    for name in ("deposits", "savings", "loans", "mortgage", "cards", "region", "calc", "market"):
        assert f".ic-{name}{{background-image:url(\"data:image/webp;base64," in css, name
