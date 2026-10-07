"""Тип ставки: базовая или на особых условиях (аудит 07.10.2026)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src import conditions, market
from src.banks import crawl_adapter as crawl


def _page(h1, *lines):
    return {"h1": h1, "title": h1, "text": "\n".join(("Меню", h1) + lines), "links": []}


def _product(bank, title, rate, category="Накопительные счета", terms=None):
    return SimpleNamespace(bank=bank, title=title, category=category, rate_min=rate,
                           rate_max=rate, apr_min=None, apr_max=None, terms=terms or {},
                           rate_conditions="", source_url="", region_method="federal")


def test_vtb_welcome_rate_two_months():
    """ВТБ-Счёт: «14,2% годовых — первые 2 месяца», базовая 6 %."""
    page = _page("Накопительный ВТБ-Счет до 14,2% годовых", "До 14,2%", "Ставка, годовых",
                 "Как увеличить ставку", "Документы", "Подробнее",
                 "14,2% годовых — первые 2 месяца", "Базовая ставка 6% годовых")
    product = crawl.product_from_page(page, bank="ВТБ", url="https://x/vtb-schet",
                                      category="Накопительные счета", region="",
                                      collected_at="")
    assert conditions.kind_of(product)[0] == conditions.WELCOME


def test_bonus_for_new_depositors_is_part_of_max_rate():
    """ВТБ-Вклад «до 13,7 %» включает надбавку «До +3,3% для новых вкладчиков»."""
    page = _page("ВТБ-Вклад в рублях до 13,7% годовых", "До 13,7%", "Ставка",
                 "Срок", "От 2 до 36 месяцев", "Сумма", "От 10 000 ₽", "Надбавки",
                 "До +1% годовых за получение зарплаты", "Подробнее",
                 "До +3,3% годовых для новых вкладчиков")
    product = crawl.product_from_page(page, bank="ВТБ", url="https://x/vtb-vklad-r",
                                      category="Вклады", region="", collected_at="")
    assert conditions.kind_of(product)[0] in (conditions.WELCOME, conditions.SALARY)


def test_first_days_about_top_up_is_not_welcome_rate():
    """Т-Банк: «первые 30 дней» — про пополнение вклада, а не про ставку."""
    page = _page("Откройте вклад со ставкой до 12,3% годовых", "До 12,3% годовых",
                 "Ставка по вкладу в рублях",
                 "Ставка по вкладу дополнительно повысится, если подключить опцию "
                 "«Непополняемый вклад». Тогда вы сможете добавлять деньги на вклад "
                 "первые 30 дней после открытия.")
    product = crawl.product_from_page(page, bank="Т-Банк", url="https://x/deposit",
                                      category="Вклады", region="", collected_at="")
    assert conditions.kind_of(product)[0] == conditions.BASE


@pytest.mark.parametrize("title, kind", [
    ("Накопительный счёт Премиум", conditions.PREMIUM),
    ("Вклад «Забота о будущем»", conditions.NICHE),
    ("Вклад с ПДС", conditions.NICHE),
    ("Вклад «Драгоценный»", conditions.NICHE),
    ("ВТБ-Вклад в юанях", conditions.NICHE),
    ("Вклад Лучший % Золотой", conditions.BASE),
])
def test_kind_by_title(title, kind):
    assert conditions.kind_of(_product("x", title, 14.0))[0] == kind


def test_special_rates_stay_out_of_sber_place():
    """Приветственные 14,2 % и 13,5 % не ставят Сбера на последнее место."""
    welcome = {conditions.TERMS_KEY: "приветственная / для новых клиентов: «первые 2 месяца»"}
    products = [
        _product("Сбер", "Накопительный счёт", 12.5),
        _product("ВТБ", "Накопительный ВТБ-Счет", 14.2, terms=welcome),
        _product("РостФинанс", "Накопительный счёт Максимум", 13.5, terms=welcome),
        _product("ЦМР", "Накопительный счет «Больше чем счет»", 12.0),
    ]
    gaps = market.build_gaps(products, home="Сбер", key_rate=14.0,
                             region_methods={"Сбер": "selector", "ВТБ": "federal",
                                             "РостФинанс": "selector", "ЦМР": "local"})
    gap = next(g for g in gaps if g.program == "Накопительные счета")
    assert gap.banks_compared == 2 and gap.rank == 1
    rows = market.specials(products, key_rate=14.0, region_methods={})
    assert {r.bank for r in rows} == {"ВТБ", "РостФинанс"}


def test_sber_details_tab_base_rate_is_not_salary():
    """Вкладка «Подробные условия» Сбера (скриншот 07.10.2026): общая ставка
    от 20,4 %, ниже — блок «Получаю зарплату или пенсию» со своими 18,4 %."""
    page = _page("Кредит наличными", "Ставки по кредиту", "Общие условия",
                 "Сумма кредита", "От 10 000 ₽", "Полная стоимость кредита1",
                 "20,400% – 50,200%", "Ставка", "От 20,4%",
                 "Получаю зарплату или пенсию в Сбере", "Сумма кредита", "От 10 000 ₽",
                 "Полная стоимость кредита1", "18,400% – 48,200%", "Ставка", "От 18,4%",
                 "Требования к заёмщику", "Гражданин РФ")
    product = crawl.product_from_page(
        page, bank="Сбер", url="https://www.sberbank.ru/ru/person/credits/money/consumer_unsecured",
        category="Кредиты", region="", collected_at="")
    assert (product.rate_min, product.apr_min, product.apr_max) == (20.4, 20.4, 50.2)
    assert conditions.kind_of(product)[0] == conditions.BASE


def test_rates_block_far_below_title_is_found():
    """Сбер: вкладка «Ставки по кредиту» внизу длинной страницы, дальше 150 строк."""
    filler = [f"Пункт описания {i}" for i in range(200)]
    page = _page("Рефинансирование", "Подробные условия", *filler, "Ставки по кредиту",
                 "Общие условия", "Полная стоимость кредита1", "17,400% – 45,200%",
                 "Ставка", "От 17,4%", "Получаю зарплату или пенсию в Сбере", "Ставка",
                 "От 15,4%", "Требования к заёмщику")
    product = crawl.product_from_page(page, bank="Сбер", url="https://x/consumer_refinance",
                                      category="Кредиты", region="", collected_at="")
    assert (product.rate_min, product.apr_min, product.apr_max) == (17.4, 17.4, 45.2)
    assert conditions.kind_of(product)[0] == conditions.BASE
