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
    ("local", "https://cmr/offices", {}, av.UNKNOWN),
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


def test_calculator_without_any_rate_does_not_prove_lnr():
    from types import SimpleNamespace
    from src import availability
    p = SimpleNamespace(terms={"Калькулятор на сайте":
                               "Луганская Народная Республика, Луганск — Семейная: калькулятор не показал расчёт"},
                        source_url="u")
    assert availability.status_of(p, region_method="federal", presence="").code != availability.LNR


def test_twin_is_chosen_by_meaning_not_by_top_rate():
    """Замечание 03.11.2026: все вклады Сбера сравнивались с «Социальным вкладом»
    ВТБ под 19 %, «Деньги до пенсии» — с газификацией 3 %, залог земли — с
    залогом авто."""
    from types import SimpleNamespace as N
    from src import availability as av

    def p(bank, title, category, rate, terms=None):
        return N(bank=bank, title=title, category=category, rate_min=rate, rate_max=rate,
                 terms=terms or {}, rate_conditions="", source_url="u")
    items = [
        p("Сбер", "Вклад Ключевой", "Вклады", 12.5), p("Сбер", "Социальный вклад", "Вклады", 22),
        p("Сбер", "Кредит наличными пенсионерам", "Кредиты", 19.4),
        p("Сбер", "Кредит под залог земельного участка", "Кредиты", 19.4),
        p("ВТБ", "ВТБ-Вклад «Ключевой»", "Вклады", 12.6), p("ВТБ", "Социальный вклад", "Вклады", 19),
        p("ВТБ", "Кредит на газификацию с господдержкой", "Кредиты", 3),
        p("ВТБ", "Кредит наличными для пенсионеров", "Кредиты", 11),
        p("ВТБ", "Кредит под залог автомобиля", "Кредиты", 19.4),
    ]
    st = {id(x): av.Status(av.LNR, "", "") for x in items}
    got = {r.product.title: (r.cells["ВТБ"].product.title if r.cells["ВТБ"].product else None)
           for r in av.matrix(items, home="Сбер", banks=["Сбер", "ВТБ"], status=st)}
    assert got["Вклад Ключевой"] == "ВТБ-Вклад «Ключевой»"
    assert got["Социальный вклад"] == "Социальный вклад"
    assert got["Кредит наличными пенсионерам"] == "Кредит наличными для пенсионеров"
    assert got["Кредит под залог земельного участка"] is None


def test_essence_rate_mechanism_and_currency():
    """По сути, а не по цифрам: плавающая ставка (от ключевой) — только с
    плавающей, юани — только с юанями, «Накопилка» — не детский продукт."""
    from types import SimpleNamespace as N

    def p(bank, title, rate, terms=None):
        return N(bank=bank, title=title, category="Вклады", rate_min=rate, rate_max=rate,
                 terms=terms or {}, rate_conditions="", source_url="u")
    items = [
        p("Сбер", "Вклад Выгодный старт", 12.5), p("Сбер", "Вклад в дирхамах", 3),
        p("Сбер", "Вклад в юанях", 1), p("Сбер", "Накопилка", 10),
        p("ВТБ", "ВТБ-Вклад «Ключевой»", 12.6), p("ВТБ", "ВТБ-Вклад в юанях", 0.9),
        p("ВТБ", "Семейная копилка", 12),
        p("Т-Банк", "Вклад", 12.3,
          {"Контекст на странице": "Ставка меняется вслед за ключевой ставкой ЦБ"}),
    ]
    st = {id(x): av.Status(av.LNR, "", "") for x in items}
    rows = {r.product.title: r for r in av.matrix(items, home="Сбер",
                                                  banks=["Сбер", "ВТБ", "Т-Банк"], status=st)}
    vtb = rows["Вклад Выгодный старт"].cells["ВТБ"]
    assert vtb.product is None or (vtb.product.title != "ВТБ-Вклад «Ключевой»" and not vtb.close)
    assert rows["Вклад Выгодный старт"].cells["Т-Банк"].product is None
    assert rows["Вклад в юанях"].cells["ВТБ"].product.title == "ВТБ-Вклад в юанях"
    assert rows["Вклад в юанях"].cells["ВТБ"].close
    assert rows["Вклад в дирхамах"].cells["ВТБ"].product is None
    assert "дети" not in av.segments(items[3])


def test_traffic_light_built_from_direct_analogs_only():
    """Ручных пар нет: светофор строится из матрицы, только прямые аналоги."""
    from types import SimpleNamespace as N
    from src.compare import GREEN, Thresholds, from_matrix

    def p(bank, title, rate, category="Кредиты"):
        return N(bank=bank, title=title, category=category, rate_min=rate, rate_max=rate,
                 apr_min=None, terms={}, rate_conditions="", source_url="u", url_path="/" + title)
    items = [p("Сбер", "Кредит наличными", 18), p("Сбер", "Кредит наличными пенсионерам", 17),
             p("ВТБ", "Кредит наличными", 20), p("ВТБ", "Кредит на газификацию с господдержкой", 3)]
    st = {id(x): av.Status(av.LNR, "", "") for x in items}
    rows = av.matrix(items, home="Сбер", banks=["Сбер", "ВТБ"], status=st)
    got = from_matrix(rows, Thresholds())
    assert [(c.sber.title, c.psb.title) for c in got] == [("Кредит наличными", "Кредит наличными")]
    assert got[0].light == GREEN


def test_essence_from_page_context():
    """«Кредит с пониженной ставкой» Сбера — кредит на покупки (рассрочка),
    «Кредит на образование» без господдержки — не аналог льготного."""
    from types import SimpleNamespace as N
    pos = N(title="Кредит с пониженной ставкой", category="Кредиты",
            terms={"Контекст на странице": "Оплачивайте товары и услуги в кредит онлайн или в магазине"})
    assert "рассрочка" in av.segments(pos)
    assert "господ" not in av.segments(N(title="Кредит на образование", terms={}))
    assert "господ" in av.segments(N(title="Кредит на образование с господдержкой", terms={}))


@pytest.mark.parametrize("title, tag, present", [
    ("Автонакопления", "авто", False),
    ("Автонакопления", "сервис", True),
    ("Автокредит", "авто", True),
    ("Вклад «Забота о будущем»", "пдс", True),
    ("ЕКПшка для детей", "дети", True),
    ("Платёжный счёт", "счёт", True),
    ("Дебетовая карта ВТБ", "счёт", False),
])
def test_essence_segments(title, tag, present):
    from types import SimpleNamespace as N
    assert (tag in av.segments(N(title=title, terms={}))) is present


def test_new_money_and_welcome_are_same_kind():
    """Решение 03.11.2026: «на новые деньги» и «для новых клиентов» — одно и то
    же; в светофоре нет пометки «тип ставки разный»."""
    from types import SimpleNamespace as N
    from src.compare import Thresholds, from_matrix
    from src import conditions as cd

    def p(bank, title, rate, kind):
        return N(bank=bank, title=title, category="Вклады", rate_min=rate, rate_max=rate,
                 apr_min=None, rate_conditions="", source_url="u", url_path="/" + title,
                 terms={cd.TERMS_KEY: cd.LABELS[kind] + ": «x»"})
    items = [p("Сбер", "СберВклад", 13.5, cd.NEW_MONEY),
             p("ВТБ", "Вклад «Выгодное начало»", 15, cd.WELCOME)]
    st = {id(x): av.Status(av.LNR, "", "") for x in items}
    got = from_matrix(av.matrix(items, home="Сбер", banks=["Сбер", "ВТБ"], status=st), Thresholds())
    assert len(got) == 1
    assert not any("Тип ставки" in n for n in got[0].notes)


@pytest.mark.parametrize("text", [
    "Кредит не предоставляется в ДНР.",
    "Программа недоступна в Донецке.",
    "Оформление невозможно, кроме жителей Херсонской области.",
])
def test_other_region_restriction_does_not_mean_lnr_restriction(text):
    assert av.find_clause(text) == ""


@pytest.mark.parametrize("code", [av.ABSENT, av.UNKNOWN, av.FEDERAL])
@pytest.mark.parametrize("side", ["own", "rival"])
def test_unconfirmed_or_absent_products_do_not_enter_lnr_traffic_light(code, side):
    from src.compare import Thresholds, from_matrix
    own = _p("Сбер", "Кредит наличными", 18)
    rival = _p("ВТБ", "Кредит наличными", 20)
    items = [own, rival]
    status = {id(p): av.Status(av.LNR, "ЛНР") for p in items}
    status[id(own if side == "own" else rival)] = av.Status(code, "проверка")
    rows = av.matrix(items, home="Сбер", banks=["Сбер", "ВТБ"], status=status)
    assert from_matrix(rows, Thresholds()) == []


def test_city_evidence_requires_exact_city_and_product_calculation():
    assert av.Status(av.LNR, "калькулятор на сайте банка: ЛНР, Луганск — ставка 18%").city_confirmed
    assert not av.Status(av.LNR, "условия получены с выбранным регионом ЛНР").city_confirmed
    assert not av.Status(av.LNR, "калькулятор на сайте банка: Луганская Народная Республика — 18%").city_confirmed
    assert not av.Status(av.FEDERAL, "банк имеет офис в Луганске").city_confirmed


def test_selected_city_is_preserved_as_product_evidence():
    product = _p("ПСБ", "Вклад", terms={"Город выбран на сайте банка": "Луганск"})
    assert av.status_of(product, region_method="selector").city_confirmed
    assert not av.status_of(product, region_method="federal", presence="офис").city_confirmed


def test_service_percentage_is_not_ranked_as_loan_interest():
    from src.compare import Thresholds, from_matrix
    items = [_p("Сбер", "Страхование квартиры", 1, category="Страхование"),
             _p("ВТБ", "Страхование квартиры", 2, category="Страхование")]
    status = {id(p): av.Status(av.LNR, "условия ЛНР") for p in items}
    rows = av.matrix(items, home="Сбер", banks=["Сбер", "ВТБ"], status=status)
    assert from_matrix(rows, Thresholds()) == []
def test_safe_deposit_city_requires_service_specific_office_list():
    from src import availability
    from src.psb.parser import Product
    p = Product(bank="Генбанк", title="Сейфовые ячейки", category="Сейфовые ячейки",
                source_url="https://www.genbank.ru/chastnym-litsam/seyfovye-yacheyki/")
    office = 'ДО «Луганск», адрес 291011, Луганская Народная Республика, г. Луганск, ул. Советская, д. 86А'
    availability.remember_service_city(p, 'Отделения банка\n' + office)
    assert availability.status_of(p, region_method="not_confirmed").code == availability.UNKNOWN
    availability.remember_service_city(p, 'Перечень ВСП, в которых предоставляется услуга:\nДО «Москва»\nМобильный банк\n' + office)
    assert availability.status_of(p, region_method="not_confirmed").code == availability.UNKNOWN
    availability.remember_service_city(p, 'Перечень ВСП, в которых предоставляется услуга:\n' + office + '\nЗаявка на аренду сейфовой ячейки')
    status = availability.status_of(p, region_method="not_confirmed")
    assert status.code == availability.LNR and status.city_confirmed
    p.terms[availability.SERVICE_SOURCE_KEY] = "https://www.genbank.ru/about/"
    assert availability.status_of(p, region_method="not_confirmed").code == availability.UNKNOWN

