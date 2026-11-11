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
    # SEO-копии продуктов из старых сборов не сравниваем: иначе их отсев
    # выглядел бы как «продукт исчез».
    from .banks.seo import is_seo_page

    return {row["product_key"]: row for row in rows
            if "source_url" not in row.keys() or not is_seo_page(row["source_url"] or "")}


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


def _banks(storage: Any, table: str, *runs: int) -> list[str]:
    """Банки, которые есть хотя бы в одном из сборов.

    Раньше список был вписан руками — ПСБ и Сбер, — и изменения у ВТБ,
    ЦМР и остальных не ловились вовсе.
    """
    marks = ",".join("?" * len(runs))
    rows = storage.conn.execute(
        f"SELECT DISTINCT bank FROM {table} WHERE run_id IN ({marks})", runs).fetchall()
    return sorted(row[0] for row in rows)


def _diff_products(storage: Any, current_run: int, previous_run: int) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for bank in _banks(storage, "products", current_run, previous_run):
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
    """Сдвиг ставки «от» и «до».

    Раньше смотрели только «от». У вклада витринная ставка — «до», и её
    снижение с 18 до 16 % при неизменной нижней границе проходило мимо.
    Верхнюю границу сверяем, только если ставка задана диапазоном, —
    иначе одно изменение дало бы два одинаковых алерта.
    """
    out: list[dict[str, Any]] = []
    single = (row["rate_max"] in (None, row["rate_min"])
              and old["rate_max"] in (None, old["rate_min"]))
    bounds = [("rate_min", "Ставка" if single else "Ставка от")]
    if not single:
        bounds.append(("rate_max", "Ставка до"))

    for column, label in bounds:
        new_rate, old_rate = row[column], old[column]
        if new_rate is None or old_rate is None or new_rate == old_rate:
            continue
        delta = round(new_rate - old_rate, 3)
        out.append({
            "bank": bank, "kind": "rate", "product_key": key, "title": row["title"],
            "field": label,
            "old_value": old["rate_raw"] or f"{old_rate}%",
            "new_value": row["rate_raw"] or f"{new_rate}%",
            "delta": delta,
            "severity": HIGH if abs(delta) >= SIGNIFICANT_RATE_PP else INFO,
        })
    return out


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

    for bank in _banks(storage, "promos", current_run, previous_run):
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
