"""Правила качества: обязательные поля, правдоподобие, сравнимость, покрытие."""

from __future__ import annotations

NA = "н/д"
REQUIRED = ("source_url", "collected_at", "region_method", "evidence")
# Ставки госпрограмм ипотеки законно ниже ключевой — их правило «кредит ниже ключевой» не трогает.
GOV_PROGRAM_PARAMS = {"rate_new_regions", "rate_family"}
LOAN_RATE_PARAMS = {
    "rate_min",
    "rate_max",
    "cc_rate_purchases",
    "rate_market_primary",
    "rate_market_secondary",
}


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def row_issues(
    row: dict, block: str, key_rate: float | None, deposit_over_key_pp: float = 3.0
) -> list[str]:
    issues = [f"missing:{f}" for f in REQUIRED if not row.get(f)]
    value, param = _num(row.get("value")), row.get("parameter", "")
    if value is None or key_rate is None:
        return issues
    if (
        block == "DEP"
        and param.startswith(("rate_", "savings_rate"))
        and value > key_rate + deposit_over_key_pp
    ):
        issues.append("recheck:deposit_above_key")
    if param in LOAN_RATE_PARAMS and param not in GOV_PROGRAM_PARAMS and value < key_rate:
        issues.append("recheck:loan_below_key")
    return issues


def product_issues(rows: list[dict]) -> list[str]:
    """Проверки, которым нужны несколько параметров одного продукта."""
    values = {r["parameter"]: _num(r.get("value")) for r in rows}
    issues = []
    for psk, rate in (
        ("psk_min", "rate_min"),
        ("psk_max", "rate_max"),
        ("cc_psk_max", "cc_rate_purchases"),
    ):
        if (
            values.get(psk) is not None
            and values.get(rate) is not None
            and values[psk] < values[rate]
        ):
            issues.append(f"psk_below_rate:{psk}<{rate}")
    return issues


def is_comparable(row: dict) -> bool:
    """В рейтинги и выводы идут только значения с подтверждённой ЛНР и нормальной уверенностью."""
    return (
        row.get("region_method") not in (None, "not_confirmed")
        and row.get("confidence") != "low"
        and row.get("value") not in (None, "", NA)
    )


def coverage(planned: list[str], rows: list[dict]) -> float:
    if not planned:
        return 0.0
    collected = {r["parameter"] for r in rows if r.get("value") not in (None, "", NA)}
    return round(100 * len(collected & set(planned)) / len(planned), 1)
