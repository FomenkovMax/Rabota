"""Финансовые расчёты. Только Decimal, никакого LLM и float."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
DAYS_IN_YEAR = Decimal(365)  # упрощение: фактические дни / 365, без учёта високосных лет


def simple_interest(amount: Decimal, annual_rate_pct: Decimal, days: int) -> Decimal:
    """Процентный доход за срок при простом начислении по номинальной ставке (без капитализации и налогов)."""
    if amount < 0 or annual_rate_pct < 0 or days < 0:
        raise ValueError("amount, rate и days не могут быть отрицательными")
    return (amount * annual_rate_pct / 100 * Decimal(days) / DAYS_IN_YEAR).quantize(CENT, rounding=ROUND_HALF_UP)
