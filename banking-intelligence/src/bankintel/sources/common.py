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


# Подпись на сайте -> устойчивое имя поля. Это сопоставление подписей, а не трактовка значений.
CONDITION_LABELS = {
    "payout": ("выплата процентов",),
    "topup": ("пополнение",),
    "withdrawal": ("расходные операции", "снятие"),
    "early_termination": ("досрочное расторжение", "досрочное закрытие"),
    "prolongation": ("пролонгация",),
    "term": ("срок действия", "срок", "срок вклада"),
    "currency": ("валюта", "валюта вклада", "валюта депозита"),
    "min_amount": ("минимальная сумма", "минимальная сумма вклада", "сумма"),
    "max_amount": ("максимальная сумма", "максимальная сумма вклада", "максимальный остаток", "максимальный остаток средств на счете"),
    "channel": ("открытие", "где открыть"),
}


def index_conditions(rows) -> dict[str, str]:
    """Первое вхождение каждой известной подписи -> {поле: сырой текст}."""
    out: dict[str, str] = {}
    for row in rows:
        label = row.label.strip().lower()
        for key, names in CONDITION_LABELS.items():
            if label in names and key not in out:
                out[key] = row.value
    return out
