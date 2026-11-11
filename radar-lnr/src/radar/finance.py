"""Оценка финансового эффекта. ВСЕГДА «≈ оценка». Нет численности — «н/д», ничего не придумываем.

ФОТ_мес   = численность × средняя з/п по отрасли (ОКВЭД, 2 знака; config/salaries.yaml)
ФОТ_год   = ФОТ_мес × 12
Потенциал = ФОТ_год × доля зачислений × доходность пакета   (коэффициенты — settings.yaml → finance)
"""
from __future__ import annotations

from .config import get_settings, load_yaml

FORMULA = ("Потенциал ≈ численность × средняя з/п по ОКВЭД × 12 мес × доля зачислений × доходность пакета. "
           "Зарплаты и коэффициенты — оценочные (config/salaries.yaml, settings.yaml → finance).")


def _rub(x: float) -> str:
    """12 345 678 -> '12,3 млн ₽'; 450 000 -> '450 тыс. ₽'."""
    if x >= 1_000_000:
        return f"{x / 1e6:.1f}".replace(".", ",") + " млн ₽"
    if x >= 1_000:
        return f"{x / 1e3:.0f} тыс. ₽"
    return f"{x:.0f} ₽"


def estimate(ev: dict, salaries: dict | None = None, fin_cfg: dict | None = None) -> dict:
    """Возвращает словарь оценки. potential_year=None, если численность неизвестна."""
    salaries = salaries or load_yaml("config/salaries.yaml")
    fin_cfg = fin_cfg or get_settings()["finance"]
    card = (ev.get("enriched") or {}).get("card") if (ev.get("enriched") or {}).get("status") == "found" else None

    employees, emp_src = None, None
    if card and card.get("employees"):
        employees, emp_src = card["employees"], "DaData"
    elif ev.get("employees_mentioned"):
        employees, emp_src = ev["employees_mentioned"], "текст новости"

    okved = (card or {}).get("okved")
    key = okved[:2] if okved else None
    by = salaries.get("by_okved2") or {}
    if key in by:
        salary, sal_src = by[key], f"ОКВЭД {key} (заглушка, TODO)"
    else:
        salary, sal_src = salaries["default"], "по умолчанию (ОКВЭД неизвестен, заглушка, TODO)"

    out = {"employees": employees, "employees_source": emp_src, "okved": okved, "salary": salary,
           "salary_source": sal_src, "fot_month": None, "fot_year": None, "potential_year": None,
           "approx": True, "formula": FORMULA}
    if employees:
        fot_m = employees * salary
        fot_y = fot_m * fin_cfg.get("months", 12)
        out.update(fot_month=fot_m, fot_year=fot_y,
                   potential_year=fot_y * fin_cfg["salary_share"] * fin_cfg["package_yield"])
    return out


def effect_text(fin: dict) -> str:
    """Короткая строка для дайджеста."""
    if fin["potential_year"] is None:
        return "н/д (численность не указана)"
    return (f"≈ {_rub(fin['potential_year'])}/год (оценка; ФОТ ≈ {_rub(fin['fot_year'])}/год, "
            f"{fin['employees']} чел. — {fin['employees_source']})")
