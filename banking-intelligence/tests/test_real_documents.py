"""Смоук на НАСТОЯЩИХ сохранённых страницах (не входят в репозиторий). Нужен REAL_DOCS_DIR=<каталог сырых документов>:
    REAL_DOCS_DIR=/path/to/raw pytest tests/test_real_documents.py
Запускать после смены вёрстки на сайтах/правок адаптеров: ловит ситуацию «сайт изменился, а парсер молча ничего не находит»."""

import os
from pathlib import Path

import pytest

from bankintel.domain.enums import ProductCategory
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchedDocument, SourceRef
from bankintel.sources.common import ParseError

ROOT = os.getenv("REAL_DOCS_DIR")
pytestmark = pytest.mark.skipif(not ROOT or not Path(ROOT).is_dir(), reason="нужен REAL_DOCS_DIR с сохранёнными страницами")

KEYS = {"psb": ["deposits", "savings_accounts", "savings_offers"], "vtb": ["deposits"]}
BASE = {"psb": "https://www.psbank.ru/personal/saving", "vtb": "https://www.vtb.ru/personal/vklady-i-scheta/"}
MIN_PRODUCTS = {"psb": 8, "vtb": 8}


def _parse_all(bank):
    adapter, found = get_adapter(bank)(bank), []
    for f in sorted((Path(ROOT) / bank).glob("*.html")):
        body = f.read_bytes()
        for key in KEYS[bank]:
            try:
                found += adapter.parse(SourceRef(key, BASE[bank], "deposit"), FetchedDocument(BASE[bank], body))
            except ParseError:
                continue
    return found


@pytest.mark.parametrize("bank", ["psb", "vtb"])
def test_real_pages_yield_products_with_rates(bank):
    products = _parse_all(bank)
    names = {(p.category, p.name) for p in products}
    assert len(names) >= MIN_PRODUCTS[bank], f"{bank}: разобрано только {len(names)} продуктов — не изменилась ли вёрстка?"
    with_rate = [p for p in products if p.params.get("headline_rate_pct")]
    assert len(with_rate) / len(products) >= 0.8, f"{bank}: у слишком многих продуктов не распознана ставка"
    for p in with_rate:
        r = p.params["headline_rate_pct"]
        hi = r["max"] or r["min"]
        assert 0 <= float(hi) <= 100
    assert {ProductCategory.DEPOSIT} <= {p.category for p in products}
