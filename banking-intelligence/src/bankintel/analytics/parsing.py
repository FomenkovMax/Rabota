"""Разбор сумм и сроков из текстов сайтов банков. Не разобрали однозначно -> None (не угадываем)."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from bankintel.sources.common import detect_currency

DAYS_IN_MONTH = Decimal(365) / 12
TERM_TOLERANCE_DAYS = 3  # «3 мес.» на сайте = 90–92 дня; допуск на округление месяцев

_NUM = r"\d{1,3}(?:[ ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_MULT = {"тыс": Decimal(1_000), "млн": Decimal(1_000_000), "млрд": Decimal(1_000_000_000)}


def months_to_days(months: int) -> int:
    """Единое правило перевода месяцев в дни (365/12, округление half-up): 3->91, 6->183, 12->365."""
    return int((Decimal(months) * DAYS_IN_MONTH).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _norm(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").replace(" ", " ").lower().split())


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(" ", "").replace(",", "."))


@dataclass(frozen=True)
class MoneyRange:
    min: Decimal | None
    max: Decimal | None
    currency: str | None


def parse_money_range(text: str | None) -> MoneyRange | None:
    """'От 10 000 ₽ до 150 000 ₽' -> (10000, 150000); 'До 50 тыс. ₽' -> (None, 50000)."""
    if not text:
        return None
    t = _norm(text)
    found = {}
    for kw, num, mult in re.findall(rf"\b(от|до)\s+({_NUM})(?:\s*(тыс|млн|млрд)\.?)?", t):
        value = _to_decimal(num) * _MULT.get(mult, Decimal(1))
        found.setdefault(kw, value)
    if not found:
        return None
    return MoneyRange(found.get("от"), found.get("до"), detect_currency(text))


@dataclass(frozen=True)
class TermSpec:
    """Допустимые сроки в днях: либо диапазон [min, max], либо набор значений."""

    min_days: int | None = None
    max_days: int | None = None
    values: tuple[int, ...] = ()

    def allows(self, days: int) -> bool:
        if self.values:
            return any(abs(days - v) <= TERM_TOLERANCE_DAYS for v in self.values)
        return self.min_days is not None and self.max_days is not None and self.min_days <= days <= self.max_days


def _unit_days(unit: str) -> Decimal | None:
    if unit.startswith("дн") or unit.startswith("сут"):
        return Decimal(1)
    if unit.startswith("мес"):
        return DAYS_IN_MONTH
    if unit.startswith("год") or unit.startswith("лет"):
        return Decimal(365)
    return None


def parse_term(text: str | None) -> TermSpec | None:
    """'91, 181 и 367 дней' -> набор; 'От 91 до 731 дня', '91 – 731 дней', '2-36 мес.' -> диапазон;
    '1 год' -> {365}. Слова вместо цифр ('до двух лет') и неоднозначности -> None."""
    if not text:
        return None
    t = _norm(text)
    tokens = re.findall(r"(\d+)\s*(дн\w*|сут\w*|мес\w*|год\w*|лет)?", t)
    if not tokens:
        return None
    # единица измерения у последнего числа распространяется на предыдущие без единицы
    unit, converted = None, []
    for num, u in reversed(tokens):
        unit = u or unit
        factor = _unit_days(unit) if unit else None
        if factor is None:
            return None
        converted.append(int((Decimal(num) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    days = list(reversed(converted))
    is_range = len(days) == 2 and (
        re.search(r"\bот\b.*\bдо\b", t) or re.search(r"\d\s*[–—\-]\s*\d", t)
    )
    if is_range:
        return TermSpec(min_days=min(days), max_days=max(days))
    if re.search(r"\bдо\b|\bот\b", t) and len(days) == 1:
        return None  # «до 2 лет» без нижней границы — не знаем, какие сроки допустимы
    return TermSpec(values=tuple(sorted(set(days))))
