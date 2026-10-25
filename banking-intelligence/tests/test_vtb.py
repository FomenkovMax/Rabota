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


# --- страницы продуктов: блоки «вопрос — ответ» (фрагменты реальных страниц ВТБ, 24.10.2026) ---

DETAIL = Path(__file__).parent / "fixtures" / "vtb_detail_faq.html"
DETAIL_REF = SourceRef("detail:1", "https://www.vtb.ru/personal/vklady-i-scheta/x/", "deposit")


def _detail(html: str | bytes):
    content = html.encode() if isinstance(html, str) else html
    return get_adapter("vtb")("vtb").parse_detail(DETAIL_REF, FetchedDocument(DETAIL_REF.url, content))


def _qa(question: str, *answer_blocks: str) -> str:
    body = "".join(f'<div class="markdown-paragraphx">{b}</div>' for b in answer_blocks)
    return (f'<div itemscope itemtype="http://schema.org/Question"><h2 itemprop="name">{question}</h2>'
            f'<div itemprop="acceptedAnswer" itemscope itemtype="http://schema.org/Answer"><div itemprop="text">{body}</div></div></div>')


def test_detail_rows_are_verbatim_question_answer_pairs():
    rows = {r.label: r.value for r in _detail(DETAIL.read_bytes())}
    assert len(rows) == 5 and all(label.startswith("Вопрос: ") for label in rows)
    assert rows["Вопрос: Можно ли изменить опции пополнения и снятия по открытому вкладу?"] == (
        "Нет, после открытия вклада эти опции изменить нельзя")
    listy = rows["Вопрос: Где можно открыть вклад?"]
    assert listy.startswith("Выберите удобный способ:\n") and listy.count("\n") >= 3  # пункты списка — отдельные строки


def test_detail_text_has_no_artifacts():
    for value in (r.value for r in _detail(DETAIL.read_bytes())):
        assert "\xa0" not in value and "  " not in value and " :" not in value and " )" not in value


def test_detail_navigation_block_is_not_a_condition():
    html = "<html>" + _qa("Вам может быть интересно", "Премиальное обслуживание") + _qa("Можно ли пополнять?", "Да") + "</html>"
    assert [r.label for r in _detail(html)] == ["Вопрос: Можно ли пополнять?"]


def test_detail_line_break_does_not_glue_words():
    html = "<html>" + _qa("Как?", "Первое<br>второе") + "</html>"
    assert _detail(html)[0].value == "Первое второе"


def test_detail_duplicates_collapsed_and_conflicting_answers_both_kept():
    same = _qa("Можно ли пополнять?", "Да")
    html = "<html>" + same + same + _qa("Можно ли пополнять?", "Нет") + "</html>"
    rows = _detail(html)
    assert [(r.label, r.value) for r in rows] == [("Вопрос: Можно ли пополнять?", "Да"), ("Вопрос: Можно ли пополнять? (2)", "Нет")]


def test_detail_layout_change_raises():
    for html in ("<html><body><h2>Условия</h2><p>Ставка 10%</p></body></html>", "<html>" + _qa("Вопрос без ответа", "") + "</html>"):
        with pytest.raises(ParseError):
            _detail(html)
