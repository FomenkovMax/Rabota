"""Сравнение текущего запуска с предыдущим: что изменилось за неделю.

Отслеживаем то, ради чего вообще нужен еженедельный запуск:
  • движение ставки (главный сигнал);
  • появление и исчезновение акций;
  • появление и уход продуктов из линейки;
  • правку условий в тарифной таблице.

Уровень важности проставляем здесь же — он определяет, что попадёт
в «шапку» отчёта и в текст уведомления.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

HIGH, MEDIUM, INFO = "high", "medium", "info"

# Сдвиг ставки крупнее этого считаем значимым для руководителя.
SIGNIFICANT_RATE_PP = 0.25


def _rows_by_key(rows: list[Any]) -> dict[str, Any]:
    return {row["product_key"]: row for row in rows}


def _promo_by_key(rows: list[Any]) -> dict[str, Any]:
    return {row["promo_key"]: row for row in rows}


def detect_changes(storage: Any, current_run: int, previous_run: int | None) -> list[dict[str, Any]]:
    """Возвращает список изменений между запусками."""
    if previous_run is None:
        log.info("Предыдущего успешного запуска нет — сравнивать не с чем")
        return []

    changes: list[dict[str, Any]] = []
    changes += _diff_products(storage, current_run, previous_run)
    changes += _diff_promos(storage, current_run, previous_run)

    log.info("Изменений найдено: %s (важных: %s)",
             len(changes), sum(1 for c in changes if c["severity"] == HIGH))
    return changes


def _diff_products(storage: Any, current_run: int, previous_run: int) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for bank in ("ПСБ", "Сбер"):
        now = _rows_by_key(storage.products_of_run(current_run, bank))
        before = _rows_by_key(storage.products_of_run(previous_run, bank))

        for key, row in now.items():
            old = before.get(key)
            if old is None:
                changes.append({
                    "bank": bank, "kind": "product_new", "product_key": key,
                    "title": row["title"], "field": "",
                    "old_value": "", "new_value": row["rate_raw"] or "—",
                    "delta": None, "severity": MEDIUM,
                })
                continue

            changes += _diff_rate(bank, key, row, old)
            changes += _diff_terms(bank, key, row, old)

        for key, row in before.items():
            if key not in now:
                changes.append({
                    "bank": bank, "kind": "product_gone", "product_key": key,
                    "title": row["title"], "field": "",
                    "old_value": row["rate_raw"] or "—", "new_value": "",
                    "delta": None, "severity": MEDIUM,
                })

    return changes


def _diff_rate(bank: str, key: str, row: Any, old: Any) -> list[dict[str, Any]]:
    new_rate, old_rate = row["rate_min"], old["rate_min"]
    if new_rate is None or old_rate is None or new_rate == old_rate:
        return []

    delta = round(new_rate - old_rate, 3)
    severity = HIGH if abs(delta) >= SIGNIFICANT_RATE_PP else INFO
    return [{
        "bank": bank, "kind": "rate", "product_key": key, "title": row["title"],
        "field": "Ставка",
        "old_value": old["rate_raw"] or f"{old_rate}%",
        "new_value": row["rate_raw"] or f"{new_rate}%",
        "delta": delta, "severity": severity,
    }]


def _diff_terms(bank: str, key: str, row: Any, old: Any) -> list[dict[str, Any]]:
    """Изменения в тарифной таблице, кроме уже пойманной ставки."""
    if row["fingerprint"] == old["fingerprint"]:
        return []

    try:
        now_terms = json.loads(row["terms_json"] or "{}")
        old_terms = json.loads(old["terms_json"] or "{}")
    except json.JSONDecodeError:
        return []

    changes: list[dict[str, Any]] = []
    for field_name, value in now_terms.items():
        previous = old_terms.get(field_name)
        if previous is None or previous == value:
            continue
        if field_name.lower().startswith("ставка"):
            continue  # уже учтено отдельно
        changes.append({
            "bank": bank, "kind": "terms", "product_key": key, "title": row["title"],
            "field": field_name, "old_value": previous[:300], "new_value": value[:300],
            "delta": None, "severity": INFO,
        })
    return changes


def _diff_promos(storage: Any, current_run: int, previous_run: int) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for bank in ("ПСБ", "Сбер"):
        now = _promo_by_key(storage.promos_of_run(current_run, bank))
        before = _promo_by_key(storage.promos_of_run(previous_run, bank))

        for key, row in now.items():
            if key not in before:
                changes.append({
                    "bank": bank, "kind": "promo_new", "product_key": row["source_path"],
                    "title": row["title"], "field": "Акция",
                    "old_value": "", "new_value": row["title"],
                    "delta": None, "severity": HIGH,
                })

        for key, row in before.items():
            if key not in now:
                changes.append({
                    "bank": bank, "kind": "promo_gone", "product_key": row["source_path"],
                    "title": row["title"], "field": "Акция",
                    "old_value": row["title"], "new_value": "",
                    "delta": None, "severity": MEDIUM,
                })

    return changes


KIND_LABEL = {
    "rate": "Изменение ставки",
    "terms": "Изменение условий",
    "promo_new": "Новая акция",
    "promo_gone": "Акция завершилась",
    "product_new": "Новый продукт",
    "product_gone": "Продукт убран",
}


def format_digest(changes: list[dict[str, Any]], *, limit: int = 25) -> str:
    """Короткая сводка для уведомления."""
    if not changes:
        return "Изменений по сравнению с прошлой неделей нет."

    important = [c for c in changes if c["severity"] in (HIGH, MEDIUM)]
    shown = important[:limit] or changes[:limit]

    lines = [f"Изменений всего: {len(changes)} (значимых: {len(important)})", ""]
    for c in shown:
        mark = {"ПСБ": "ПСБ", "Сбер": "Сбер"}.get(c["bank"], c["bank"])
        head = f"[{mark}] {KIND_LABEL.get(c['kind'], c['kind'])}: {c['title'][:90]}"
        if c["kind"] == "rate" and c["delta"] is not None:
            arrow = "вырос" if c["delta"] > 0 else "снижен"
            head += f" — {arrow} на {abs(c['delta']):.2f} п.п. ({c['old_value']} → {c['new_value']})"
        elif c["field"] and c["kind"] == "terms":
            head += f" — «{c['field']}»"
        lines.append(head)

    if len(important) > limit:
        lines.append(f"…и ещё {len(important) - limit} изменений — смотри в отчёте")
    return "\n".join(lines)
