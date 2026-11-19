import pytest

from src import availability, securities
from src.psb.liquid_securities import SCOPE, parse


DOCUMENT = """Список ценных бумаг для совершения необеспеченных сделок на 18.11.2026
Акции
1 SBER Сбербанк Акция обыкновеннаяlong/short ПАО «Сбербанк»
Облигации
1RU000A10AXW4 СибурХ1Р03 Биржевая облигация long ПАО «СИБУР Холдинг»
Фонды
1 AKME Пай биржевого фонда long
"""


def test_specific_margin_issues_are_listed_without_local_availability():
    share, bond = parse(DOCUMENT)
    assert share.terms["Тикер"] == "SBER"
    assert securities.ISIN not in share.terms
    assert share.terms["Маржинальная позиция"] == "long/short"
    assert bond.terms[securities.ISIN] == "RU000A10AXW4"
    for product in (share, bond):
        assert product.collected_at == "2026-11-18"
        assert product.terms[securities.DOCUMENT_SCOPE] == SCOPE
        assert availability.status_of(product, region_method="selector").code == availability.UNKNOWN
    assert len(securities.groups([share, bond])) == 2


def test_missing_numbered_row_rejects_document():
    with pytest.raises(ValueError, match="Строка 1"):
        parse(DOCUMENT.replace("1RU000", "2RU000"))
