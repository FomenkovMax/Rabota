"""Есть ли продукт в Луганске — статус и основание (ТЗ, 28.10.2026)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src import availability as av
from src import market


def _p(bank, title, rate=10.0, category="Кредиты", terms=None, method=""):
    return SimpleNamespace(bank=bank, title=title, category=category, rate_min=rate,
                           rate_max=rate, terms=terms or {}, source_url=f"https://{bank}/x",
                           region_method=method)


@pytest.mark.parametrize("method, presence, terms, code", [
    ("selector", "", {}, av.LNR),
    ("local", "https://cmr/offices", {}, av.LNR),
    ("federal", "https://bankprofi.ru/...", {}, av.FEDERAL),
    ("federal", "", {}, av.UNKNOWN),
    ("not_confirmed", "x", {}, av.UNKNOWN),
    ("selector", "", {market.REGION_KEY: "калькулятор: недоступно"}, av.ABSENT),
    ("federal", "x", {"Калькулятор на сайте": "Луганская Народная Республика, Луганск — "
                                              "Квартира в новостройке: 18,9 %"}, av.LNR),
])
def test_status_rules(method, presence, terms, code):
    st = av.status_of(_p("Банк", "Кредит", terms=terms), region_method=method, presence=presence)
    assert st.code == code and st.reason


@pytest.mark.parametrize("text, found", [
    ("Кредит не предоставляется жителям ДНР, ЛНР, Запорожской и Херсонской областей.", True),
    ("Программа недоступна в новых регионах.", True),
    ("Оформление во всех регионах, кроме Луганской Народной Республики.", True),
    ("Льготная ипотека для жителей новых регионов под 2%.", False),
    ("Кредит не выдаётся без подтверждения дохода.", False),
])
def test_find_clause(text, found):
    assert bool(av.find_clause(text)) is found


def test_matrix_finds_twin_and_marks_missing():
    sber = _p("Сбер", "Семейная ипотека", 7.0, "Ипотека", method="selector")
    psb = _p("ПСБ", "Семейная ипотека", 6.0, "Ипотека", method="federal")
    vtb = _p("ВТБ", "Ипотека на новостройку", 18.0, "Ипотека", method="federal")
    products = [sber, psb, vtb]
    status = av.statuses(products, region_methods={}, presence={"ПСБ": "src"})
    rows = av.matrix(products, home="Сбер", banks=["Сбер", "ПСБ", "ВТБ"], status=status)
    row = rows[0]
    assert row.own.code == av.LNR
    assert row.cells["ПСБ"].status.code == av.FEDERAL and row.cells["ПСБ"].rate == 6.0
    assert row.cells["ВТБ"].status is None
    assert av.completeness(products, status, home="Сбер")[av.LNR] == 1


def test_clause_on_page_marks_product_absent():
    from src.banks import crawl_adapter as crawl
    page = {"h1": "Кредит наличными", "title": "Кредит наличными", "links": [],
            "text": "Меню\nКредит наличными\nСтавка от 20,4%\n"
                    "Кредит не предоставляется жителям ДНР и ЛНР."}
    product = crawl.product_from_page(page, bank="Банк", url="https://x/credit",
                                      category="Кредиты", region="", collected_at="")
    assert "ДНР и ЛНР" in product.terms[market.REGION_KEY]
