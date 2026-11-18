from src import securities, availability
from src.psb.parser import Product


def instrument(bank="Банк", title="Акции Сбербанка", url="https://bank.example/stocks/sber"):
    return Product(bank=bank, title=title, category="Инвестиции", source_url=url)


def test_isin_checksum_and_unambiguous_issue_matching():
    a, b = instrument(), instrument("Другой банк", "Сбербанк обыкновенные")
    for p in (a, b):
        securities.remember(p, ["ISIN", "RU0009029540"])
        assert p.terms[securities.ISIN] == "RU0009029540"
    assert len(securities.groups([a, b])) == 1
    assert not securities.valid_isin("RU0009029541")


def test_missing_or_ambiguous_isin_never_merges_issues():
    a, b = instrument(), instrument("Другой банк")
    securities.remember(a, ["RU0009029540", "RU0009029557"])
    securities.remember(b, [])
    assert securities.ISIN not in a.terms
    assert len(securities.groups([a, b])) == 2


def test_city_selector_does_not_prove_security_can_be_bought():
    p = instrument()
    securities.remember(p, ["RU0009029540"])
    p.terms["Город выбран на сайте банка"] = "Луганск"
    status = availability.status_of(p, region_method="selector")
    assert status.code == availability.UNKNOWN
    assert not status.city_confirmed


def test_coupon_is_preserved_as_source_text_not_bank_rate():
    p = instrument(title="Облигация эмитента", url="https://bank.example/bonds/example")
    securities.remember(p, ["Купон", "12%", "Дата погашения", "01.12.2028"])
    assert p.terms["Купон"] == "Купон: 12%"
    assert p.rate_min is None


def test_tbank_uses_document_isin_for_ofz_instead_of_url_slug():
    p = instrument(title="ОФЗ 26218", url="https://www.tbank.ru/invest/bonds/SU26218RMFS6")
    securities.remember(p, [], page_title="Купить облигации ОФЗ 26218 (RU000A0JVW48) 📈: цена")
    assert p.terms[securities.ISIN] == "RU000A0JVW48"


def test_registry_renders_sources_and_keeps_different_issues_separate():
    from src.report import _securities_block
    a, b = instrument(), instrument("Другой банк", "Привилегированные акции")
    securities.remember(a, ["RU0009029540"])
    securities.remember(b, ["RU0009029557"])
    html = _securities_block({a.bank: [a], b.bank: [b]})
    assert "RU0009029540" in html and "RU0009029557" in html
    assert "Доступность покупки в Луганске не подтверждена" in html


def test_lessons_and_market_overviews_are_not_security_issues():
    for url, title in [
        ("https://bank.example/investments/edu/courses/bonds/lesson", "Урок 5. Облигации"),
        ("https://bank.example/investments/bonds", "Облигации в валюте"),
        ("https://bank.example/investments/stocks/offer", "Купить акции"),
    ]:
        p = instrument(title=title, url=url)
        securities.remember(p, [])
        assert securities.KIND not in p.terms


def test_legacy_lesson_metadata_does_not_enter_registry():
    p = instrument(title="Рынок акций", url="https://bank.example/investments/stocks")
    p.terms[securities.KIND] = "Акция"
    assert securities.groups([p]) == []


def test_partial_collection_keeps_distinct_issues_with_same_name(tmp_path):
    from datetime import datetime

    from src.banks.base import CollectResult
    from src.pipeline import _keep_unread
    from src.storage import Storage

    older = instrument("Т-Банк", "Облигации эмитента", "https://www.tbank.ru/invest/bonds/old")
    newer = instrument("Т-Банк", older.title, "https://www.tbank.ru/invest/bonds/new")
    older.url_path, newer.url_path = "/invest/bonds/old", "/invest/bonds/new"
    older.collected_at = datetime.now().isoformat()
    storage = Storage(tmp_path / "snapshots.db")
    try:
        before = storage.start_run("ЛНР")
        after = storage.start_run("ЛНР")
        storage.save_products(before, [older])
        storage.save_products(after, [newer])
        result = CollectResult(bank="Т-Банк", products=[newer], partial=True)
        _keep_unread(storage, result, before, after)
        assert {row["source_url"] for row in storage.products_of_run(after)} == {
            older.source_url, newer.source_url,
        }
    finally:
        storage.close()
