"""Формулы сценариев. Ставки — в % годовых, срок — в месяцах, месяц = 1/12 года."""

from __future__ import annotations


def annuity_payment(principal: float, annual_rate_pct: float, months: int) -> float:
    if months <= 0:
        raise ValueError("Срок должен быть больше нуля")
    r = annual_rate_pct / 1200
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def overpayment(principal: float, annual_rate_pct: float, months: int) -> float:
    return annuity_payment(principal, annual_rate_pct, months) * months - principal


def deposit_income(
    amount: float, annual_rate_pct: float, months: int, capitalization: bool
) -> float:
    r = annual_rate_pct / 1200
    if capitalization:
        return amount * ((1 + r) ** months - 1)
    return amount * r * months


def effective_rate(annual_rate_pct: float) -> float:
    """Эффективная ставка при ежемесячной капитализации, % годовых."""
    return ((1 + annual_rate_pct / 1200) ** 12 - 1) * 100


def debit_card_annual_benefit(
    monthly_spend: float,
    cashback_pct: float,
    cashback_limit_month: float,
    balance: float,
    balance_rate_pct: float,
    service_fee_month: float,
) -> float:
    cashback_month = min(monthly_spend * cashback_pct / 100, cashback_limit_month)
    return 12 * cashback_month + balance * balance_rate_pct / 100 - 12 * service_fee_month


def credit_card_annual_cost(
    service_fee_month: float, cash_amount: float, cash_fee_pct: float, cash_fee_min: float
) -> float:
    """Покупки гасятся в льготный период, поэтому проценты по ним не начисляются."""
    cash_fee = max(cash_amount * cash_fee_pct / 100, cash_fee_min) if cash_amount else 0.0
    return 12 * service_fee_month + cash_fee
