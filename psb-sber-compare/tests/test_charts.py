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
