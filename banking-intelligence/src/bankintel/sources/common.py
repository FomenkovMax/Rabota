"""Общие функции разбора российских банковских страниц (используются адаптерами)."""

import re
from decimal import Decimal

from bs4 import Tag

_NUM = r"\d+(?:[.,]\d+)?"
_NAME_IN_QUOTES = re.compile(r"«([^»]+)»")
# «Ұ» (кириллическая) встречается на сайте ВТБ вместо знака юаня — реальная особенность данных.
_CURRENCY = {"₽": "RUB", "¥": "CNY", "Ұ": "CNY", "$": "USD", "€": "EUR"}


class ParseError(Exception):
    """Страница получена, но ожидаемой структуры в ней нет."""


def clean_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())
    return text or None


def parse_rate_range(text: str) -> tuple[Decimal | None, Decimal | None] | None:
    """'От 16% до 20%' -> (16, 20); 'До 16% годовых' -> (None, 16); '28,0%' -> (28.0, 28.0).
    Возвращает None, если однозначно разобрать нельзя."""
    t = text.replace("\xa0", " ").lower()
    nums = [Decimal(n.replace(",", ".")) for n in re.findall(_NUM, t)]
    if not nums or "%" not in t:
        return None
    if t.startswith("до") and len(nums) == 1:
        return None, nums[0]
    if t.startswith("от") and len(nums) == 1:
        return nums[0], None
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2:
        return min(nums), max(nums)
    return None


def detect_currency(text: str) -> str | None:
    for sym, code in _CURRENCY.items():
        if sym in text:
            return code
    return None


def canonical_name(title: str) -> str:
    m = _NAME_IN_QUOTES.search(title)
    return m.group(1).strip() if m else title.strip()


def rate_json(text: str) -> dict | None:
    r = parse_rate_range(text)
    if r is None:
        return None
    return {"min": str(r[0]) if r[0] is not None else None, "max": str(r[1]) if r[1] is not None else None}
