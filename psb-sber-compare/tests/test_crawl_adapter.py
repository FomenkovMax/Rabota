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


def test_single_bank_refresh_keeps_other_banks(tmp_path):
    """«Обновить данные → Только ПСБ» не должно стирать Сбер из свода."""
    from src.psb.parser import Product
    from src.storage import Storage

    storage = Storage(tmp_path / "db.sqlite")
    first = storage.start_run("ЛНР")
    storage.save_products(first, [
        Product(bank="Сбер", title="Вклад «Сбер Рядом»", rate_max=14.0,
                collected_at="2026-10-01T07:00"),
        Product(bank="ПСБ", title="Вклад «Мой доход»", rate_max=13.8,
                collected_at="2026-10-01T07:00"),
    ])
    storage.finish_run(first, psb=1, sber=1, promos=0)

    second = storage.start_run("ЛНР")
    storage.save_products(second, [Product(bank="ПСБ", title="Вклад «Мой доход»",
                                           rate_max=14.1, collected_at="2026-10-05T12:00")])
    assert storage.carry_over(first, second, except_bank="ПСБ") == 1

    rows = {r["bank"]: r for r in storage.products_of_run(second)}
    assert set(rows) == {"Сбер", "ПСБ"}
    assert rows["ПСБ"]["rate_max"] == 14.1                       # свежее
    assert rows["Сбер"]["collected_at"] == "2026-10-01T07:00"     # дата прежняя


def test_region_rule_three_cases():
    """Правило заказчика: про ЛНР на сайте ничего — единые условия по РФ."""
    from src.banks.base import region_binding

    cookies = {"region_cookies": [{"name": "r", "value": "94"}],
               "region_label": "Луганская Народная Республика"}
    assert region_binding(False, cookies) == ("selector", "Луганская Народная Республика")
    assert region_binding(True, {"region_label": "ЛНР"}) == ("selector", "ЛНР")

    method, label = region_binding(False, {"region_mode": "federal"})
    assert method == "federal" and "единые условия по РФ" in label

    # Регион выбирается, но не задан: это Москва по адресу сервера, а не
    # «единые условия», — правило сюда не относится.
    assert region_binding(False, {})[0] == "not_confirmed"


def test_federal_bank_is_compared_not_warned(monkeypatch):
    monkeypatch.setattr(crawl, "PageReader", FakeReader)
    result = OnlyCredits(region=None, settings={"max_pages": 50,
                                                "region_mode": "federal"}).collect()
    assert result.region_applied and result.region_method == "federal"
    assert all("единые условия по РФ" in p.region for p in result.products)
    assert "единые условия по РФ" in result.summary


# --- ошибки, найденные в первом полном сборе (06.10.2026) -------------------

def _page(h1, *lines):
    return {"h1": h1, "title": h1, "text": "\n".join(("Меню", h1) + lines), "links": []}


def test_down_payment_caption_is_not_a_rate():
    """«от 20,1%» с подписью «первоначальный взнос» строкой ниже — не ставка."""
    data = _page("Семейная ипотека", "от 20,1%", "Первоначальный взнос",
                 "от 6%", "Ставка")
    product = crawl.product_from_page(data, bank="Сбер", url="https://x/ru/home/family",
                                      category="Ипотека", region="ЛНР", collected_at="")
    assert (product.rate_min, product.rate_raw) == (6.0, "от 6%")


def test_share_of_property_value_is_not_a_rate():
    data = _page("Кредит под залог недвижимости",
                 "Сумма до 80% от стоимости недвижимости", "от 19,9%")
    product = crawl.product_from_page(data, bank="Сбер", url="https://x/ru/credits/pledge",
                                      category="Кредиты", region="ЛНР", collected_at="")
    assert product.rate_min == 19.9


def test_service_pages_are_not_products():
    for title in ("Ипотечные каникулы", "Программы поддержки заёмщиков",
                  "Управляйте списаниями за подписки и покупки",
                  "Открыть СберВклад в СберБанке онлайн", "sberbank.ru"):
        assert crawl.product_from_page(_page(title, "30%"), bank="Сбер", url="https://x/a",
                                       category="Кредиты", region="", collected_at="") is None
    assert crawl.is_product_title("Платёжный стикер от Сбера")
    assert crawl.is_product_title("Кредит наличными")


def test_showcase_caption_above_rate_is_respected():
    """Витрина Сбера: ставка над названием, но перед ней подпись «взнос»."""
    from src.banks.generic_site import extract_products

    text = "\n".join([
        "до 14%", "Вклад «Сбер Рядом»", "Онлайн",
        "до 13,5%", "Вклад «Лучший %»", "Онлайн",
        "Первоначальный взнос", "от 20,1%", "Семейная ипотека", "Новостройки",
    ])
    found = {p.title: p.rate_min for p in extract_products(text)}
    assert found.get("Вклад «Сбер Рядом»") == 14.0
    assert "Семейная ипотека" not in found


def test_check_bank_saves_page_texts(monkeypatch, tmp_path):
    """check-bank кладёт тексты страниц в папку — для разбора по архиву."""
    monkeypatch.setattr(crawl, "PageReader", FakeReader)
    adapter = OnlyCredits(region=None, settings={
        "region_cookies": [{"name": "r", "value": "94"}], "max_pages": 50,
        "pages_dir": str(tmp_path / "pages"),
    })
    assert adapter.collect().ok
    files = sorted(p.name for p in (tmp_path / "pages").iterdir())
    assert files[0] == "000-summary.txt" and len(files) > 2
    page = (tmp_path / "pages" / files[1]).read_text(encoding="utf-8")
    assert page.startswith("URL: https://") and "ТЕКСТ:" in page


def test_local_bank_counts_as_lnr():
    """ЦМР работает только в ЛНР: условия его сайта — луганские, не «по РФ»."""
    from src.banks.base import region_binding
    from src.pipeline import Config, bank_region_methods

    method, label = region_binding(False, {"region_mode": "local"})
    assert method == "local" and "только в ЛНР" in label
    assert bank_region_methods(Config.load(), ["cmr"]) == {"ЦМР": "local"}


def test_seo_duplicates_are_skipped():
    skip = SberAdapter.skip
    for path in ("/ru/person/credits/money/na_50000_rublej",
                 "/ru/person/credits/money/kredit_s_18_let",
                 "/ru/person/contributions/deposits/vklad-na-3-mesyaca",
                 "/ru/person/bank_cards/credit_cards/s_limitom_30000",
                 "/ru/person/credits/money/kazan"):
        assert skip.search(path), path
    for path in ("/ru/person/credits/money/consumer_unsecured",
                 "/ru/person/bank_cards/credit_cards/credit_sberkarta",
                 "/ru/person/credits/home/family",
                 "/ru/person/contributions/deposits/vklad_kluchevoy"):
        assert not skip.search(path), path


def test_most_linked_page_is_read_first():
    from collections import deque

    queue = deque(["https://x/seo-1", "https://x/product", "https://x/seo-2"])
    popularity = {"https://x/seo-1": 1, "https://x/product": 30, "https://x/seo-2": 1}
    assert crawl.CrawlAdapter._next(queue, popularity) == "https://x/product"
    assert crawl.CrawlAdapter._next(queue, popularity) == "https://x/seo-1"


BLOCK_PAGE = {"h1": "", "title": "sberbank.ru", "links": [],
              "text": "Возникла проблема при открытии сайта Сбербанка в этом браузере.\n"
                      "Support ID: <8935934556078563006>"}


def test_protection_stub_is_not_a_product_and_stops_politely(monkeypatch, tmp_path):
    """Заглушка защиты: пауза, повтор, при повторной заглушке — стоп без мусора."""
    class Blocking(FakeReader):
        reads = 0

        def close(self):
            pass

        def read(self, url):
            Blocking.reads += 1
            if Blocking.reads > 3:
                return dict(BLOCK_PAGE)
            return super().read(url)

    monkeypatch.setattr(crawl, "PageReader", Blocking)
    adapter = OnlyCredits(region=None, settings={
        "region_cookies": [{"name": "r", "value": "94"}], "max_pages": 50,
        "block_pause_s": 0, "pages_dir": str(tmp_path / "pages"),
    })
    result = adapter.collect()
    assert result.ok
    assert all(p.title != "sberbank.ru" for p in result.products)
    summary = (tmp_path / "pages" / "000-summary.txt").read_text(encoding="utf-8")
    assert "закрыл доступ" in summary


def test_slow_seed_is_retried_at_the_end(monkeypatch):
    """Витрина не отдалась с первого раза — вторая попытка позже, не подряд."""
    calls: list[str] = []

    class SlowFirst(FakeReader):
        def read(self, url):
            calls.append(url)
            if len(calls) == 1:
                raise PageTooSlow("страница не отдалась за 90 с")
            return super().read(url)

    monkeypatch.setattr(crawl, "PageReader", SlowFirst)
    adapter = OnlyCredits(region=None, settings={
        "region_cookies": [{"name": "r", "value": "94"}], "max_pages": 50})
    assert adapter.collect().ok
    # Вторая попытка — не сразу, а когда браузер уже прогрет другими страницами.
    assert calls.count(calls[0]) == 2 and calls[1] != calls[0]


def test_priority_products_are_read_right_after_seeds(monkeypatch):
    calls: list[str] = []

    class Recording(FakeReader):
        def read(self, url):
            calls.append(url)
            return super().read(url)

    class WithPriority(OnlyCredits):
        priority = (f"{BASE}/ru/person/credits/money/refinancing",)

    monkeypatch.setattr(crawl, "PageReader", Recording)
    WithPriority(region=None, settings={"region_cookies": [{"name": "r", "value": "9"}],
                                        "max_pages": 50}).collect()
    assert calls[len(OnlyCredits.seeds)] == f"{BASE}/ru/person/credits/money/refinancing"


def test_sber_savings_account_family():
    adapter = SberAdapter(region=None, settings={})
    assert adapter._family(f"{BASE}/ru/person/contributions/deposits/nakopi") == "Накопительные счета"
    assert adapter._family(f"{BASE}/ru/person/contributions/deposits/vklad") == "Вклады"


def test_share_of_price_and_miles_are_not_rates():
    from src.banks.generic_site import rates_of

    assert rates_of("Платите 25% стоимости товара на терминале") is None
    assert rates_of("+50% миль") is None
    assert rates_of("Ставка до 13,5% годовых") == [13.5]


def test_partial_crawl_keeps_unread_products_from_last_run(tmp_path):
    """Сбер оборвал обход — непрочитанные продукты берутся из прошлого сбора.

    Но не мусор: не дубли свежих по названию, не страницы-услуги и не
    цифры старше двух недель.
    """
    from datetime import datetime, timedelta

    from src.banks.base import CollectResult
    from src.pipeline import _keep_unread
    from src.psb.parser import Product
    from src.storage import Storage

    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    old_date = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    storage = Storage(tmp_path / "db.sqlite")
    old = storage.start_run("ЛНР")
    storage.save_products(old, [
        Product(bank="Сбер", url_path="/deposits", title="Вклад «Сбер Рядом»",
                rate_max=14.0, collected_at=yesterday),
        Product(bank="Сбер", url_path="/vklad", title="Вклад", rate_max=13.0,
                collected_at=yesterday),
        Product(bank="Сбер", url_path="/homenew#семейная ипотека", title="Семейная ипотека",
                rate_min=20.1, collected_at=yesterday),
        Product(bank="Сбер", url_path="/kanikuly", title="Ипотечные каникулы",
                rate_min=30.0, collected_at=yesterday),
        Product(bank="Сбер", url_path="/archive", title="Вклад «Старый»",
                rate_max=9.0, collected_at=old_date),
    ])
    storage.finish_run(old, psb=0, sber=5, promos=0)

    new = storage.start_run("ЛНР")
    fresh = [Product(bank="Сбер", url_path="/vklad", title="Вклад", rate_max=13.5),
             Product(bank="Сбер", url_path="/credits/home/family", title="Семейная ипотека")]
    storage.save_products(new, fresh)
    _keep_unread(storage, CollectResult(bank="Сбер", products=fresh, partial=True), old, new)

    rows = {r["title"]: r for r in storage.products_of_run(new)}
    assert set(rows) == {"Вклад", "Семейная ипотека", "Вклад «Сбер Рядом»"}
    assert rows["Вклад"]["rate_max"] == 13.5                  # свежее не затёрто
    assert rows["Семейная ипотека"]["rate_min"] is None       # копия со взносом не вернулась
    assert rows["Вклад «Сбер Рядом»"]["collected_at"] == yesterday

    # Полный обход ничего не переносит: пропавший продукт действительно пропал.
    third = storage.start_run("ЛНР")
    storage.save_products(third, fresh)
    _keep_unread(storage, CollectResult(bank="Сбер", products=fresh), new, third)
    assert len(storage.products_of_run(third)) == 2


def test_education_loan_and_sber_credit_card_categories():
    from src import market
    from src.banks.generic_site import category_for
    from src.psb.parser import Product

    loan = Product(bank="Сбер", title="Кредит на образование с господдержкой",
                   category="Кредиты", rate_min=3.0, rate_max=3.0)
    assert market.program_of(loan) == "Образовательный кредит"
    assert market.assess(loan, key_rate=14.0, region_method="selector").usable
    assert category_for("Кредитная СберКарта", "Банковские карты") == "Кредитные карты"


def test_showcase_short_title_merges_into_product_page():
    from src.psb.parser import Product

    adapter = OnlyCredits(region=None, settings={})
    page = Product(bank="Сбер", url_path="/credits/obrazovanie",
                   title="Кредит на образование с господдержкой", rate_min=3.0, rate_max=3.0)
    item = type("Item", (), {"title": "Кредит на образование", "rate_min": 3.0,
                             "rate_max": 3.0, "rate_raw": "3%"})()
    merged = adapter._merge({crawl.normalize_title(page.title): page},
                            {crawl.normalize_title(item.title): (item, f"{BASE}/x", "Кредиты")},
                            "ЛНР", "")
    assert [p.title for p in merged] == ["Кредит на образование с господдержкой"]


def test_new_bank_without_known_sections_is_crawled_by_url_words(monkeypatch):
    """Т-Банк и РостФинанс: разделы по словам в адресе, без списка families."""
    from src.banks.others import RostfinanceAdapter

    pages = {
        "https://www.rostfinance.ru/": {
            "h1": "", "title": "РостФинанс", "text": "Частным лицам",
            "links": [["https://www.rostfinance.ru/vklady/dohodny", "Вклад"],
                      ["https://www.rostfinance.ru/business/rko", "РКО"]]},
        "https://www.rostfinance.ru/vklady/dohodny": {
            "h1": "Вклад «Доходный»", "title": "", "links": [],
            "text": "Меню\nВклад «Доходный»\nСтавка до 15,5% годовых\nСрок 6 месяцев"},
    }

    class Reader:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def close(self):
            pass

        def read(self, url):
            if url not in pages:
                raise PageFailed(f"{url} → HTTP 404")
            return pages[url]

    monkeypatch.setattr(crawl, "PageReader", Reader)
    result = RostfinanceAdapter(region=None, settings={"region_mode": "federal"}).collect()
    assert result.ok, result.error
    assert [(p.title, p.category, p.rate_max) for p in result.products] == [
        ("Вклад «Доходный»", "Вклады", 15.5)]


def test_not_found_page_is_not_a_product():
    page = {"h1": "Классический Рост", "text": "404\nТАКОЙ СТРАНИЦЫ НЕТ :(\nЛУЧШИЕ ПРЕДЛОЖЕНИЯ"}
    assert crawl.is_not_found(page)
    assert not crawl.is_not_found({"h1": "Вклад", "text": "Ставка до 14%"})


def test_tbank_advertising_headline_becomes_product_name():
    assert crawl.product_name("Оформите кредит наличными онлайн") == "Кредит наличными"
    assert crawl.product_name("Откройте вклад со ставкой до 12,3% годовых") == "Вклад"
    assert crawl.product_name("Откройте накопительный счет") == "Накопительный счет"
    assert crawl.product_name("Кредит на авто") == "Кредит на авто"


def test_showcase_psk_and_down_payment_captions():
    from src.banks.generic_site import extract_products

    tbank = "\n".join(["Ипотека на вторичное жилье", "Максимальная сумма 50 млн рублей",
                       "Полная стоимость кредита 17,016 – 24,135%", "Ставка от 16,9%",
                       "Срок кредитования до 30 лет"])
    assert [(p.title, p.rate_min) for p in extract_products(tbank)] == [
        ("Ипотека на вторичное жилье", 16.9)]
    rostfin = "\n".join(["Ипотека для новых регионов", "ОТ 10,1%", "первый взнос",
                         "Кредит под залог авто", "ДО 70%", "от рыночной стоимости авто"])
    assert extract_products(rostfin) == []


def test_keep_trailing_slash_for_rostfinance():
    from src.banks.others import RostfinanceAdapter, TbankAdapter

    url = "https://www.rostfinance.ru/deposits/gorizonty-rosta/"
    assert RostfinanceAdapter(region=None, settings={})._normalize(url) == url
    assert TbankAdapter(region=None, settings={})._normalize(
        "https://www.tbank.ru/loans/cash-loan/") == "https://www.tbank.ru/loans/cash-loan"
    assert TbankAdapter.skip.search("/cards/debit-cards/dlya-studentov")
    assert not TbankAdapter.skip.search("/cards/debit-cards/tinkoff-black")


def test_error_pages_and_tbank_deposit_family():
    from src.banks.others import TbankAdapter

    assert crawl.is_not_found({"h1": "502 Bad Gateway", "text": "502 Bad Gateway"})
    adapter = TbankAdapter(region=None, settings={})
    assert adapter._family("https://www.tbank.ru/savings/deposit") == "Вклады"
    assert adapter._family("https://www.tbank.ru/savings/saving-account") == "Накопительные счета"


def test_rostfinance_service_pages_and_bonus_caption():
    from src.banks.generic_site import rates_of  # noqa: F401

    for title in ("ВКЛАДЫ И CЧЕТА", "СТРАХОВАНИЕ ВКЛАДОВ", "СПОСОБЫ ПОПОЛНЕНИЯ КАРТЫ",
                  "выпуск карты", "Соотношение кредит/залог в процентах"):
        assert not crawl.is_product_title(title), title
    for title in ("Горизонты Роста", "IT-ипотека", "Кредитная карта", "Карта ЦМР.Плюс"):
        assert crawl.is_product_title(title), title
    page = _page("Кредитная карта", "62 дня", "льготный период", "до 1%", "начисление бонусов")
    product = crawl.product_from_page(page, bank="РостФинанс", url="https://x/cards/credit-card/",
                                      category="Кредитные карты", region="", collected_at="")
    assert product.rate_min is None


def test_priority_page_with_subpages_is_a_product(monkeypatch):
    """«Кредит наличными» Т-Банка ссылается на подстраницы, но это продукт."""
    from src.banks.others import TbankAdapter

    root = "https://www.tbank.ru"
    cash = {"h1": "Оформите кредит наличными онлайн", "title": "", "text":
            "Меню\nОформите кредит наличными онлайн\nНа любые цели",
            "links": [[f"{root}/loans/cash-loan/{x}"] for x in ("auto", "realty", "pension")]}

    class Reader:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def close(self):
            pass

        def read(self, url):
            if url == f"{root}/loans/cash-loan":
                return cash
            raise PageFailed("нет")

    class OnlyCash(TbankAdapter):
        seeds = (f"{root}/loans",)
        priority = (f"{root}/loans/cash-loan/",)

    monkeypatch.setattr(crawl, "PageReader", Reader)
    result = OnlyCash(region=None, settings={"region_mode": "federal"}).collect()
    assert [p.title for p in result.products] == ["Кредит наличными"]


def test_bonus_caption_above_the_number():
    page = _page("Кредитная карта", "Начисление бонусов по программе лояльности",
                 "до 1%", "годовых")
    product = crawl.product_from_page(page, bank="РостФинанс", url="https://x/cards/credit-card/",
                                      category="Кредитные карты", region="", collected_at="")
    assert product.rate_min is None


def test_deposit_title_wins_over_savings_section():
    from src.banks.generic_site import category_for

    assert category_for("Пополняемый вклад", "Накопительные счета") == "Вклады"
    assert category_for("Накопительный счет для ближайших целей", "Накопительные счета") \
        == "Накопительные счета"


def test_plural_card_headings_are_not_products():
    assert not crawl.is_product_title("Банковские карты с кешбэком и бонусами")
    assert not crawl.is_product_title("Дебетовые карты для путешествий")
    assert crawl.is_product_title("Дебетовая карта Black")


def test_vtb_first_check_junk():
    from src.banks.generic_site import rates_of

    for title in ("Вклады в Самаре", "Вклады на 1 год", "Вклады с капитализацией",
                  "Накопительные счета в Санкт-Петербурге", "Сберегательные вклады",
                  "Курс покупки и продажи золота", "Монеты из драгоценных металлов",
                  "Обезличенный металлический счет", "Услуги по размещению сбережений"):
        assert not crawl.is_product_title(title), title
    for title in ("Накопительный ВТБ-Счет в рублях", "ВТБ-Вклад", "Ипотека на новых территориях"):
        assert crawl.is_product_title(title), title
    assert crawl.is_not_found({"h1": "Такой страницы не существует. Вероятно, она", "text": ""})
    assert rates_of("Ставка ниже до 5%") is None
    assert rates_of("Оплачивайте до 99% чека") is None
    assert rates_of("до 13,7% годовых") == [13.7]
