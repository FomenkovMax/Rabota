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


def test_office_link_and_lugansk_quote():
    from src.banks import crawl_adapter as crawl
    links = [["https://www.vtb.ru/personal/ipoteka", "Ипотека"],
             ["https://other.ru/offices", "Офисы"],
             ["https://www.vtb.ru/offices/", "Офисы и банкоматы"]]
    assert crawl.office_link(links, "https://www.vtb.ru") == "https://www.vtb.ru/offices/"
    assert crawl.lugansk_quote("Москва\nЛуганск\nДонецк") == ""
    quote = crawl.lugansk_quote("Офис «Луганский»\nг. Луганск, ул. Советская, 54\nПн–Пт 9:00–18:00")
    assert "ул. Советская" in quote


def test_presence_prefers_office_address_over_article():
    from src import pipeline
    from src.banks.crawl_adapter import OFFICES_KEY, OFFICES_PROOF_KEY
    config = pipeline.Config(raw={"banks": {"vtb": {"presence_source": "статья"},
                                            "tbank": {"presence_source": "статья"}}})
    links = {"ВТБ": {OFFICES_KEY: "https://www.vtb.ru/offices/",
                     OFFICES_PROOF_KEY: "г. Луганск, ул. Советская, 54"},
             "Т-Банк": {OFFICES_KEY: "https://www.tbank.ru/offices/",
                        OFFICES_PROOF_KEY: "на странице офисов банка Луганск не найден"}}
    out = pipeline.bank_presence(config, ["vtb", "tbank"], links)
    assert out["ВТБ"].startswith("страница офисов банка") and "Советская" in out["ВТБ"]
    assert out["Т-Банк"].startswith("статья (на странице офисов банка Луганск не найден")


def test_savings_account_titles_are_accounts():
    from src.banks.generic_site import category_for
    assert category_for("Сберегательный счёт", "Вклады") == "Накопительные счета"
    assert category_for("Вклад до востребования СберБанка России", "Вклады") == "Накопительные счета"
    assert category_for("Вклад Выгодный старт", "Вклады") == "Вклады"
