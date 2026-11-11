"""Расчёт сценариев по опубликованным условиям продукта (calc_method = agent_formula).

Недостающие входные данные дают «н/д» со списком нехватки — значения не подставляются.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lnrbank.calc import formulas as f

NA = "н/д"
MTG_PROGRAMS = {
    "new_regions": "rate_new_regions",
    "family": "rate_family",
    "market_primary": "rate_market_primary",
    "market_secondary": "rate_market_secondary",
}


@dataclass
class ScenarioResult:
    scenario_id: str
    status: str = "ok"
    metrics: dict[str, float] = field(default_factory=dict)
    by_program: dict[str, dict[str, float]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    assumptions: list[str] = field(default_factory=list)
    calc_method: str = "agent_formula"


def _need(params: dict, names: list[str]) -> list[str]:
    return [n for n in names if params.get(n) is None]


def _na(sid: str, missing: list[str] | None = None, reason: str = "") -> ScenarioResult:
    if missing and not reason:
        reason = "нет данных: " + ", ".join(missing)
    return ScenarioResult(sid, status=NA, missing=missing or [], reason=reason)


def compute_scenario(sid: str, spec: dict, params: dict) -> ScenarioResult:
    product = spec["product"]
    handler = {
        "deposit": _deposit,
        "savings_account": _savings,
        "debit_card": _debit_card,
        "credit_card": _credit_card,
        "cash_loan": _loan,
        "car_loan": _car_loan,
        "mortgage": _mortgage,
    }.get(product)
    if handler is None:
        raise ValueError(f"Неизвестный продукт сценария {sid}: {product}")
    return handler(sid, spec, params)


def _deposit(sid, spec, p):
    rate_key = f"rate_{spec['term_months']}m_online"
    missing = _need(p, [rate_key, "capitalization"])
    if missing:
        return _na(sid, missing)
    rate, cap = float(p[rate_key]), bool(p["capitalization"])
    income = f.deposit_income(spec["amount"], rate, spec["term_months"], cap)
    res = ScenarioResult(sid, metrics={"rate": rate, "income": round(income, 2)})
    if cap:
        res.metrics["effective_rate"] = round(f.effective_rate(rate), 3)
    res.assumptions.append("месяц = 1/12 года")
    return res


def _savings(sid, spec, p):
    missing = _need(p, ["savings_rate_base"])
    if missing:
        return _na(sid, missing)
    months, amount = spec["term_months"], spec["amount"]
    welcome_months = min(int(p.get("savings_welcome_months") or 0), months)
    welcome_rate = p.get("savings_rate_welcome")
    if welcome_months and welcome_rate is None:
        return _na(sid, ["savings_rate_welcome"])
    income = f.deposit_income(amount, float(welcome_rate or 0), welcome_months, False)
    income += f.deposit_income(
        amount, float(p["savings_rate_base"]), months - welcome_months, False
    )
    res = ScenarioResult(sid, metrics={"income": round(income, 2)})
    res.assumptions.append("проценты на постоянный остаток, без капитализации")
    return res


def _debit_card(sid, spec, p):
    names = ["cashback_base_pct", "cashback_limit_month", "balance_rate", "service_fee_month"]
    missing = _need(p, names)
    if missing:
        return _na(sid, missing)
    benefit = f.debit_card_annual_benefit(
        spec["monthly_spend"],
        float(p["cashback_base_pct"]),
        float(p["cashback_limit_month"]),
        spec["balance"],
        float(p["balance_rate"]),
        float(p["service_fee_month"]),
    )
    res = ScenarioResult(sid, metrics={"annual_benefit": round(benefit, 2)})
    res.assumptions.append("базовый кэшбэк; условия бесплатного обслуживания не учитываются")
    return res


def _credit_card(sid, spec, p):
    missing = _need(p, ["service_fee_month", "cc_cash_fee_pct", "cc_cash_fee_min", "cc_grace_days"])
    if missing:
        return _na(sid, missing)
    cost = f.credit_card_annual_cost(
        float(p["service_fee_month"]),
        spec["cash_withdrawal"],
        float(p["cc_cash_fee_pct"]),
        float(p["cc_cash_fee_min"]),
    )
    res = ScenarioResult(
        sid, metrics={"annual_cost": round(cost, 2), "grace_days": float(p["cc_grace_days"])}
    )
    if p.get("cc_grace_kept_after_cash") is False:
        res.assumptions.append("льготный период теряется после снятия — проценты не включены")
    return res


def _loan_metrics(principal: float, rate: float, months: int) -> dict[str, float]:
    return {
        "rate": rate,
        "payment": round(f.annuity_payment(principal, rate, months), 2),
        "overpayment": round(f.overpayment(principal, rate, months), 2),
    }


def _loan(sid, spec, p):
    missing = _need(p, ["rate_min"])
    if missing:
        return _na(sid, missing)
    if p.get("amount_max") is not None and spec["amount"] > float(p["amount_max"]):
        return _na(sid, reason="сумма сценария больше максимальной")
    res = ScenarioResult(
        sid, metrics=_loan_metrics(spec["amount"], float(p["rate_min"]), spec["term_months"])
    )
    if p.get("psk_min") is not None:
        res.metrics["psk"] = float(p["psk_min"])
    res.assumptions.append("по минимальной ставке «от» из опубликованных условий")
    return res


def _car_loan(sid, spec, p):
    missing = _need(p, ["rate_min", "car_down_payment_min_pct"])
    if missing:
        return _na(sid, missing)
    if spec["down_payment_pct"] < float(p["car_down_payment_min_pct"]):
        return _na(sid, reason="ПВ сценария меньше минимального")
    principal = spec["price"] * (1 - spec["down_payment_pct"] / 100)
    res = ScenarioResult(
        sid, metrics=_loan_metrics(principal, float(p["rate_min"]), spec["term_months"])
    )
    res.assumptions.append("по минимальной ставке «от» из опубликованных условий")
    return res


def _mortgage(sid, spec, p):
    if p.get("down_payment_min_pct") is None:
        return _na(sid, ["down_payment_min_pct"])
    if spec["down_payment_pct"] < float(p["down_payment_min_pct"]):
        return _na(sid, reason="ПВ сценария меньше минимального")
    principal = spec["price"] * (1 - spec["down_payment_pct"] / 100)
    if p.get("loan_max") is not None and principal > float(p["loan_max"]):
        return _na(sid, reason="сумма кредита больше лимита")
    wanted = {
        "primary": ("new_regions", "family", "market_primary"),
        "secondary": ("new_regions", "family", "market_secondary"),
    }[spec["market"]]
    res = ScenarioResult(sid)
    for program in wanted:
        rate = p.get(MTG_PROGRAMS[program])
        if rate is not None:
            res.by_program[program] = _loan_metrics(principal, float(rate), spec["term_months"])
    if not res.by_program:
        return _na(sid, [MTG_PROGRAMS[x] for x in wanted])
    return res
