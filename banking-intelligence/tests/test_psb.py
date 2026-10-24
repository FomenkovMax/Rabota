from decimal import Decimal
from pathlib import Path

import pytest

from bankintel.domain.enums import AvailabilityStatus, CollectionStatus, FetchOutcome, ProductCategory
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchDiagnostic, FetchedDocument, SourceRef
from bankintel.sources.psb import ParseError, canonical_name, parse_rate_range

FIX = Path(__file__).parent / "fixtures"  # фрагменты реальных страниц ПСБ от 24.10.2026
DEP = SourceRef("deposits", "https://www.psbank.ru/personal/saving", "deposit")
SAV = SourceRef("savings_accounts", "https://www.psbank.ru/personal/savingsaccount", "savings")
OFF = SourceRef("savings_offers", "https://www.psbank.ru/personal/savingsoffers", "savings")


def parse(src, fixture):
    html = (FIX / fixture).read_bytes()
    return get_adapter("psb")("psb").parse(src, FetchedDocument(src.url, html))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("От 16% до 20%", (16, 20)),
        ("От\xa010,8% до 14,5%", (Decimal("10.8"), Decimal("14.5"))),
        ("До 16% годовых", (None, 16)),
        ("28,0%", (Decimal("28.0"), Decimal("28.0"))),
        ("От 13,3 до 14,3%", (Decimal("13.3"), Decimal("14.3"))),
        ("5% годовых", (5, 5)),
        ("Начисление %", None),
        ("Без ограничений", None),
    ],
)
def test_parse_rate_range(text, expected):
    assert parse_rate_range(text) == expected


def test_canonical_name():
    assert canonical_name("Вклад «Мой доход»") == "Мой доход"
    assert canonical_name("Накопительный счет «Акцент на процент»") == "Акцент на процент"
    assert canonical_name("«Народный вклад»") == "Народный вклад"
    assert canonical_name("Без кавычек") == "Без кавычек"


def by_name(products):
    return {p.name: p for p in products}


def test_deposit_cards():
    ps = by_name(parse(DEP, "psb_deposits_cards.html"))
    assert set(ps) == {"Мой доход", "Народный вклад", "В юанях", "Социальный вклад", "Стабильный доход"}
    p = ps["Мой доход"]
    assert p.category == ProductCategory.DEPOSIT
    assert p.params["headline_rate_text"] == "От 12,00% до 14,10%"
    assert p.params["headline_rate_pct"] == {"min": "12.00", "max": "14.10"}
    assert p.params["amount_text"] == "От 50 000 ₽" and p.params["currency"] == "RUB"
    assert "term_text" not in p.params  # на карточке срока нет — не выдумываем
    assert p.params["product_url"] == "https://www.psbank.ru/personal/saving/myincome"
    assert p.evidence["headline_rate_text"] == "От 12,00% до 14,10%"


def test_relative_href_without_slash_and_currency():
    ps = by_name(parse(DEP, "psb_deposits_cards.html"))
    assert ps["Стабильный доход"].params["product_url"] == "https://www.psbank.ru/personal/saving/stabilnyi-dokhod"
    assert ps["В юанях"].params["currency"] == "CNY"
    assert ps["Социальный вклад"].params["headline_rate_pct"] == {"min": "28.0", "max": "28.0"}


def test_savings_cards_bonus_not_confused_with_rate():
    ps = by_name(parse(SAV, "psb_savings_cards.html"))
    acc = ps["Акцент на процент"]
    assert acc.category == ProductCategory.SAVINGS
    assert acc.params["headline_rate_text"] == "До 16% годовых"  # а не «+5% годовых»
    zapas = ps["Про запас"]
    assert zapas.params["headline_rate_label"] == "Доход в первые 2 месяца"
    assert zapas.params["base_rate_text"] == "5% годовых"
    assert zapas.params["base_rate_pct"] == {"min": "5", "max": "5"}


def test_category_follows_product_url_on_offers_page():
    """На странице «спецпредложений» лежат и вклады, и счета — категория по ссылке карточки."""
    ps = parse(OFF, "psb_deposits_cards.html")
    assert all(p.category == ProductCategory.DEPOSIT for p in ps)
    ps = parse(OFF, "psb_savings_cards.html")
    assert all(p.category == ProductCategory.SAVINGS for p in ps)
    assert all(p.params["page_key"] == "savings_offers" for p in ps)


def test_lnr_never_confirmed_by_card():
    for p in parse(DEP, "psb_deposits_cards.html"):
        assert p.lnr_status == AvailabilityStatus.NOT_CONFIRMED and p.lnr_quote is None


def test_unknown_source_ignored_and_no_cards_is_error():
    adapter = get_adapter("psb")("psb")
    root = SourceRef("site_root", "https://www.psbank.ru", "discovery")
    assert adapter.parse(root, FetchedDocument(root.url, b"<html/>")) == []
    with pytest.raises(ParseError):
        adapter.parse(DEP, FetchedDocument(DEP.url, b"<html><body>redesign</body></html>"))


class _Fetcher:
    def __init__(self, pages):
        self.pages = pages

    async def fetch(self, source):
        html = self.pages[source.key]
        return FetchedDocument(source.url, html), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


async def test_layout_change_is_partial_not_silent():
    pages = {"deposits": (FIX / "psb_deposits_cards.html").read_bytes(), "savings_accounts": b"<html>new layout</html>"}
    res = await get_adapter("psb")("psb", _Fetcher(pages)).collect([DEP, SAV])
    assert res.status == CollectionStatus.PARTIAL
    assert len(res.products) == 5 and len(res.documents) == 2  # документы сохранены
    assert any("parse_error" in m and "savings_accounts" in m for m in res.messages)
