"""Автоаудит: поиск значения на странице, выборка, баллы охвата."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src import audit, coverage


@pytest.mark.parametrize("value, text, found", [
    (14.8, "Вклад Лучший % Золотой\nдо 14,8%", True),
    (14.8, "до 14,80 % годовых", True),
    (14.8, "до 114,8%", False),
    (14.8, "до 14,85%", False),
    (2.0, "Ставка от 2%", True),
    (2.0, "срок 2 года", False),
    (27.9, "Ставка - 27,9% годовых", True),
    (18.662, "ПСК 18,662 – 25,643%", True),
])
def test_find_value(value, text, found):
    assert bool(audit.find_value(text, value)) is found


def test_excerpt_prefers_line_with_percent():
    text = "Сумма 14,8 тыс. ₽\nСтавка до 14,8%"
    assert "%" in audit.find_value(text, 14.8)


def test_sample_takes_every_bank_and_category():
    def p(bank, category, rate):
        return SimpleNamespace(bank=bank, category=category, title=f"{bank} {category} {rate}",
                               rate_min=rate, rate_max=rate, terms={}, rate_conditions="")
    products = [p("Сбер", "Вклады", r) for r in (10, 11, 12)] + [
        p("ВТБ", "Ипотека", 2), p("ВТБ", "Страхование", None)]
    sample = audit.pick_sample(products, per_cell=2)
    assert len([s for s in sample if s.bank == "Сбер"]) == 2
    assert any(s.bank == "ВТБ" and s.category == "Ипотека" for s in sample)
    assert all(s.category != "Страхование" for s in sample)


def test_cell_points_follow_agreed_scope():
    # По категориям со ставками — сравнение, по остальным — достаточно ссылки.
    assert audit._cell_points("Вклады", coverage.COMPARED, False) == 1.0
    assert audit._cell_points("Вклады", coverage.LINK_ONLY, False) == 0.3
    assert audit._cell_points("Инвестиции", coverage.LINK_ONLY, False) == 1.0
    assert audit._cell_points("Инвестиции", coverage.NOT_FOUND, False) == 0.0
    assert audit._cell_points("Ипотека", coverage.NOT_FOUND, True) is None


def test_verify_marks_found_missing_and_unreachable():
    class Fetcher:
        def text(self, code, url):
            if "down" in url:
                raise RuntimeError("timeout")
            return "Ставка до 13,7%"

    def p(title, rate, url):
        return SimpleNamespace(bank="ВТБ", title=title, category="Вклады", rate_min=rate,
                               rate_max=rate, source_url=url, terms={}, rate_conditions="")

    evidence = audit.verify([p("A", 13.7, "https://x/a"), p("B", 12.0, "https://x/b"),
                             p("C", 13.7, "https://x/down")], Fetcher(), {}, {})
    assert [e.status for e in evidence] == [audit.FOUND, audit.MISSING, audit.UNREACHABLE]
