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
