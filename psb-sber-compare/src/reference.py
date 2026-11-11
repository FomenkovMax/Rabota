"""Эталон продуктов банка: всё ли нашёл сбор.

Сбор находит продукт, только если дошёл до его страницы. Чего он не видит,
о том молчит: «СберБлиже» (/ru/sberblizhe) и «СберВклад» (страница с
заголовком «Открыть СберВклад…») находил заказчик, а не бот (02.11.2026).
Эталон — список продуктов банка в config/reference_<код>.yaml; после каждого
сбора бот пишет, каких продуктов из него нет в собранном.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]

#: Откуда продукт в эталоне — для подписи в отчёте.
SOURCES = {
    "site": "страница на сайте банка",
    "aggregator": "есть на агрегаторе, сбор на сайте банка не нашёл — проверить",
    "site-text": "упоминается на сайте банка, своей страницы сбор не нашёл",
}


@dataclass
class Check:
    bank: str
    total: int
    found: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def share(self) -> str:
        return f"{len(self.found)} из {self.total}"


def load(code: str, *, folder: Path = ROOT / "config") -> dict[str, Any]:
    path = folder / f"reference_{code.lower()}.yaml"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[«»\"'.,:;!?()]+", " ", (text or "").lower().replace("ё", "е")).split())


def _found(item: dict[str, Any], products: list[Any]) -> Any:
    path = (item.get("path") or "").rstrip("/")
    pattern = item.get("match")
    name = _norm(item.get("name", ""))
    for product in products:
        url = getattr(product, "source_url", "") or ""
        own = urlsplit(url).path.rstrip("/")
        if path and own == path:
            return product
        title = getattr(product, "title", "") or ""
        if pattern and re.search(pattern, title, re.I):
            return product
        if not pattern and name and _norm(title) == name:
            return product
    return None


def check(reference: dict[str, Any], products: Iterable[Any]) -> Check | None:
    """Сверка эталона с собранными продуктами банка."""
    bank = reference.get("bank")
    items = [i for i in reference.get("products") or [] if i.get("active", True)]
    if not bank or not items:
        return None
    own = [p for p in products if getattr(p, "bank", "") == bank]
    out = Check(bank=bank, total=len(items))
    for item in items:
        (out.found if _found(item, own) else out.missing).append(item)
    return out
