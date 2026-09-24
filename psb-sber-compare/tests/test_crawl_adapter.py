"""Обход каталога по ссылкам — на страницах, повторяющих вёрстку Сбера."""

from __future__ import annotations

import pytest

import src.banks.crawl_adapter as crawl
from src.banks.browser import PageFailed, PageTooSlow
from src.banks.others import SberAdapter

BASE = "https://www.sberbank.ru"


def page(h1: str, text: str, links: list[str] = ()) -> dict:
    menu = "Частным клиентам\nСамозанятым\nМалому бизнесу и ИП\nМеню\n"
    return {"h1": h1, "title": f"{h1} — оформить онлайн | СберБанк",
            "text": menu + text, "links": [[BASE + l, ""] for l in links]}


PAGES = {
    # Витрина кредитов: у карточек только сумма и срок, ставок нет.
    f"{BASE}/ru/person/credits/money": page("Кредиты", "\n".join([
        "Кредиты", "Кредит наличными", "Нужен только паспорт", "от 10 000 ₽",
        "сумма", "до 5 лет", "срок", "Подробнее", "Рефинансирование",
        "Объедините любые кредиты в один", "от 10 000 ₽", "Подробнее",
    ]), [
        "/ru/person/credits/money/consumer",
        "/ru/person/credits/refinance",
        "/ru/person/credits/education",
        "/ru/person/credits/auto",
        "/ru/person/credits/calculator",          # служебное — мимо
        "/ru/s_m_business/credits",               # бизнес — мимо
    ]),
    f"{BASE}/ru/person/credits/money/consumer": page("Кредит наличными", "\n".join([
        "Кредит наличными", "Ставка от 19,9% годовых", "Сумма до 5 млн ₽",
        "Срок до 5 лет", "Другие предложения", "Автокредит", "от 15,5%",
    ]), ["/ru/person/credits/auto"]),
    # Цифра есть только ниже «Вопросов и ответов» — она не про этот продукт.
    f"{BASE}/ru/person/credits/refinance": page("Рефинансирование", "\n".join([
        "Рефинансирование", "Объедините кредиты в один", "от 10 000 ₽",
        "до 5 лет", "Вопросы и ответы", "Ставка от 10% годовых по другой программе",
    ])),
    f"{BASE}/ru/person/credits/education": page("Кредит на образование", "\n".join([
        "Кредит на образование", "3,000%", "ПСК", "от 1 семестра",
    ])),
    f"{BASE}/ru/person/credits/auto": "hang",

    # Витрина вкладов: ставка над названием.
    f"{BASE}/ru/person/contributions": page("Вклады и счета", "\n".join([
        "Вклады и счета", "до 14%", "Вклад «Сбер Рядом»", "От 30 000 ₽, от 1 месяца",
        "Подробнее", "до 12,5%", "Накопительный счёт Рядом", "От 0 ₽, бессрочный",
        "Подробнее", "до 14,8%", "Вклад Лучший %", "От 100 000 ₽, от 1 месяца",
    ]), [
        "/ru/person/contributions/deposits/vklad/sber_ryadom",
        "/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent",
        "/ru/person/contributions/calculator",
    ]),
    # Страница вклада без цифры — ставка должна прийти с витрины.
    f"{BASE}/ru/person/contributions/deposits/vklad/sber_ryadom": page(
        "Вклад «Сбер Рядом»", "\n".join([
            "Вклад «Сбер Рядом»", "Откройте вклад онлайн", "От 30 000 ₽",
        ])),
    f"{BASE}/ru/person/contributions/deposits/vklad/vklad_luchshiy_procent": page(
        "Вклад Лучший %", "\n".join([
            "Вклад Лучший %", "до 14,8%", "годовых", "От 100 000 ₽, от 1 месяца",
        ])),
}


class FakeReader:
    def __init__(self, settings, **kwargs):
        self.read_urls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def read(self, url):
        self.read_urls.append(url)
        found = PAGES.get(url)
        if found == "hang":
            raise PageTooSlow(f"страница не отдалась за 90 с: {url}")
        if found is None:
            raise PageFailed(f"нет страницы {url}")
        return found


class OnlyCredits(SberAdapter):
    seeds = (f"{BASE}/ru/person/credits/money", f"{BASE}/ru/person/contributions")


@pytest.fixture
def collected(monkeypatch):
    monkeypatch.setattr(crawl, "PageReader", FakeReader)
    adapter = OnlyCredits(region=None, settings={
        "region_label": "Луганская Народная Республика",
        "region_cookies": [{"name": "sbrf.region_id", "value": "94",
                            "domain": "www.sberbank.ru"}],
        "max_pages": 50,
    })
    result = adapter.collect()
    assert result.ok, result.error
    return {p.title: p for p in result.products}, result


def test_every_product_is_kept_even_without_rate(collected):
    products, _ = collected
    assert "Рефинансирование" in products
    refinance = products["Рефинансирование"]
    assert refinance.rate_min is None
    assert refinance.terms["Ставка"] == "на странице продукта не указана"


def test_rate_below_questions_block_is_not_taken(collected):
    """Цифра под «Вопросами и ответами» — про другую программу."""
    products, _ = collected
    assert products["Рефинансирование"].rate_min is None


def test_rate_from_product_page(collected):
    products, _ = collected
    consumer = products["Кредит наличными"]
    assert (consumer.rate_min, consumer.rate_raw) == (19.9, "Ставка от 19,9% годовых")
    assert consumer.amount_max == 5_000_000
    assert consumer.term_max_months == 60


def test_cross_sell_rate_is_not_attached(collected):
    """Автокредит «от 15,5%» из подборки не должен стать ставкой кредита наличными."""
    products, _ = collected
    assert products["Кредит наличными"].rate_min == 19.9


def test_psk_is_stored_as_psk_not_as_rate(collected):
    products, _ = collected
    education = products["Кредит на образование"]
    assert education.rate_min is None
    assert education.apr_min == 3.0
    assert education.terms["Ставка"] == "на странице указана только ПСК"


def test_showcase_rate_fills_page_without_rate(collected):
    products, _ = collected
    deposit = products["Вклад «Сбер Рядом»"]
    assert deposit.rate_max == 14.0
    assert "витрине" in deposit.terms["Источник ставки"]


def test_showcase_only_product_is_added_with_its_category(collected):
    products, _ = collected
    savings = products["Накопительный счёт Рядом"]
    assert savings.rate_max == 12.5
    assert savings.category == "Накопительные счета"


def test_page_rate_wins_over_showcase(collected):
    products, _ = collected
    best = products["Вклад Лучший %"]
    assert best.rate_max == 14.8
    assert "Источник ставки" not in best.terms


def test_hanging_page_does_not_stop_crawl(collected):
    products, result = collected
    assert "Автокредит" not in products        # страница зависла
    assert "Кредит наличными" in products      # а обход дошёл до остальных


def test_service_and_business_links_are_not_followed(monkeypatch):
    reader = FakeReader(None)
    monkeypatch.setattr(crawl, "PageReader", lambda *a, **k: reader)
    OnlyCredits(region=None, settings={"max_pages": 50}).collect()
    visited = " ".join(reader.read_urls)
    assert "calculator" not in visited
    assert "s_m_business" not in visited


def test_listing_page_is_not_a_product(collected):
    products, _ = collected
    assert "Кредиты" not in products
    assert "Вклады и счета" not in products


def test_region_is_labelled_only_with_cookies(monkeypatch):
    monkeypatch.setattr(crawl, "PageReader", FakeReader)
    result = OnlyCredits(region=None, settings={"max_pages": 50}).collect()
    assert not result.region_applied
    assert all(p.region == "регион на сайте не выбран" for p in result.products)


def test_categories(collected):
    products, _ = collected
    assert products["Кредит наличными"].category == "Кредиты"
    assert products["Вклад Лучший %"].category == "Вклады"
