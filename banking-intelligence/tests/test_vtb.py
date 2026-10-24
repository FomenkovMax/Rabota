from pathlib import Path

import pytest

from bankintel.domain.enums import AvailabilityStatus, CollectionStatus, ProductCategory
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchedDocument, SourceRef
from bankintel.sources.common import ParseError

FIX = Path(__file__).parent / "fixtures" / "vtb_cards.html"  # фрагмент реальной страницы, 24.10.2026
SRC = SourceRef("deposits", "https://www.vtb.ru/personal/vklady-i-scheta/", "deposit")


@pytest.fixture(scope="module")
def products():
    adapter = get_adapter("vtb")("vtb")
    ps = adapter.parse(SRC, FetchedDocument(SRC.url, FIX.read_bytes()))
    return {p.name: p for p in ps}


def test_all_product_cards_found_promo_blocks_skipped(products):
    # 14 блоков на странице: 12 продуктов + 2 текстовых промо-блока без цифр
    assert len(products) == 12
    assert "Инвестиционный+" in products  # название взято из alt картинки: у карточки нет текстового заголовка


def test_deposit_fields(products):
    p = products["Выгодное начало"]
    assert p.category == ProductCategory.DEPOSIT
    assert p.params["headline_rate_text"] == "15%"
    assert p.params["headline_rate_pct"] == {"min": "15", "max": "15"}
    assert p.params["amount_text"] == "От 10 000 ₽"
    assert p.params["term_text"] == "3 мес."
    assert p.params["currency"] == "RUB"
    assert p.params["product_url"] == "https://www.vtb.ru/personal/vklady-i-scheta/vigodnoe-nachalo/"
    assert p.evidence["headline_rate_text"] == "15%"


def test_key_rate_deposit_has_rate_and_yield_separately(products):
    p = products["Ключевой"]
    assert p.params["headline_rate_text"] == "До 12,6%"
    assert p.params["yield_text"] == "До 15,21%"
    assert p.params["yield_pct"] == {"min": None, "max": "15.21"}


def test_accounts_classified_as_savings(products):
    assert products["День в плюсе"].category == ProductCategory.SAVINGS
    assert products["Семейная копилка"].category == ProductCategory.SAVINGS
    assert products["Накопительный ВТБ-Счет в рублях"].category == ProductCategory.SAVINGS
    assert products["ВТБ-Вклад в рублях"].category == ProductCategory.DEPOSIT
    assert products["Двойная выгода"].category == ProductCategory.DEPOSIT


def test_account_without_term_has_no_term_and_no_invented_amount(products):
    p = products["День в плюсе"]
    assert "term_text" not in p.params and "amount_text" not in p.params
    # «От 1 000 ₽» под подписью «Начисление процентов» оставлено сырым в advantages, без трактовки
    assert {"value": "От 1 000 ₽", "label": "Начисление процентов"} in p.params["advantages"]


def test_yuan_sign_variants(products):
    assert products["ВТБ-Вклад в юанях"].params["currency"] == "CNY"  # на сайте «Ұ» (кириллическая)
    assert products["Накопительный ВТБ-Счет в юанях"].params["currency"] == "CNY"


def test_rate_ranges_and_terms(products):
    assert products["Социальный вклад"].params["headline_rate_pct"] == {"min": None, "max": "19"}
    assert products["Двойная выгода"].params["term_text"] == "3, 6, 12 мес."
    assert products["ВТБ-Вклад в рублях"].params["term_text"] == "2-36 мес."


def test_lnr_not_confirmed(products):
    assert all(p.lnr_status == AvailabilityStatus.NOT_CONFIRMED and p.lnr_quote is None for p in products.values())


def test_layout_change_raises_and_other_sources_ignored():
    adapter = get_adapter("vtb")("vtb")
    with pytest.raises(ParseError):
        adapter.parse(SRC, FetchedDocument(SRC.url, b"<html><body>redesign</body></html>"))
    root = SourceRef("site_root", "https://www.vtb.ru", "discovery")
    assert adapter.parse(root, FetchedDocument(root.url, b"<html/>")) == []


async def test_collect_partial_when_markup_breaks():
    class F:
        async def fetch(self, source):
            from bankintel.domain.enums import FetchOutcome
            from bankintel.sources.base import FetchDiagnostic

            return FetchedDocument(source.url, b"<html>x</html>"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)

    res = await get_adapter("vtb")("vtb", F()).collect([SRC])
    assert res.status == CollectionStatus.FAILED and "parse_error" in res.messages[0] and res.documents
