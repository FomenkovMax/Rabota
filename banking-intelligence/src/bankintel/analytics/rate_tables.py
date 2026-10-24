"""Таблицы ставок «сумма × срок» (банк публикует точную ставку для сочетания, а не диапазон «до X %»).

Формат таблицы (нормализован адаптером банка, хранится в params карточки):
  {"fixed_terms": bool, "min_term": int, "max_term": int,
   "tiers": [{"id", "min_sum", "replenish", "withdraw",
              "terms": [{"id", "days", "at_end": "12.5"|None, "monthly": "12.1"|None}]}]}
Порядок ступеней и сроков — как их перебирает калькулятор банка (по возрастанию числового id): от него зависит результат.
`lookup` — порт логики калькулятора ЦМР; проверяется на эталоне, снятом с настоящего калькулятора (tests/test_cmr.py).
"""

from dataclasses import dataclass
from decimal import Decimal

TERM_TOLERANCE_DAYS = 3  # месяц сценария ≈ 30,4 дня, у банка «1 мес.» = 31 дню


@dataclass(frozen=True)
class RateQuote:
    rate: Decimal
    term_days: int
    replenish: bool
    withdraw: bool


def nearest_fixed_term(table: dict, days: int, tol: int = TERM_TOLERANCE_DAYS) -> int | None:
    """Для вкладов с фиксированными сроками: ближайший допустимый срок в пределах допуска (365 -> 367)."""
    if table["tiers"]:
        options = [t["days"] for t in table["tiers"][0]["terms"]]
        close = [d for d in options if abs(d - days) <= tol]
        return min(close, key=lambda d: (abs(d - days), d)) if close else None
    return None


def lookup(
    table: dict, amount: Decimal | int, days: int, payout: str = "at_end", *, need_replenish: bool = False, need_withdraw: bool = False
) -> RateQuote | None:
    """Ставка для суммы и срока или None, если банк для них продукт не предлагает.
    payout: 'at_end' — проценты в конце срока; любое другое значение — ежемесячная выплата."""
    amount = Decimal(amount)
    if not (table["min_term"] <= days <= table["max_term"]):
        return None
    tier = None
    for t in table["tiers"]:  # последняя ступень, для которой сумма достаточна
        if amount >= Decimal(str(t["min_sum"])):
            tier = t
    if tier is None:
        return None
    entry, used, prev = None, days, None
    for e in tier["terms"]:
        if table["fixed_terms"]:
            if days == e["days"]:
                entry = e
            elif days < e["days"] and entry is None and prev is not None:
                entry, used = prev, prev["days"]  # срока нет в списке -> ближайший меньший
        elif days >= e["days"]:
            entry = e
        prev = e
    if entry is None:
        return None
    if (need_replenish and not tier["replenish"]) or (need_withdraw and not tier["withdraw"]):
        return None
    raw = entry["at_end" if payout == "at_end" else "monthly"]
    rate = Decimal(raw) if raw is not None else None
    if rate is None or rate <= 0:
        return None
    return RateQuote(rate, used, bool(tier["replenish"]), bool(tier["withdraw"]))


def max_rate(table: dict) -> Decimal | None:
    rates = [Decimal(e[k]) for t in table["tiers"] for e in t["terms"] for k in ("at_end", "monthly") if e[k] is not None]
    return max(rates, default=None)
