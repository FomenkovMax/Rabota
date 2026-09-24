"""Что делает бот под кнопками.

Слой между Telegram и пайплайном: бот отвечает за диалог, здесь — работа
с данными. Никаких aiogram-типов, чтобы всё это можно было проверить
обычным скриптом.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from src.ai import consultant
from src.compare import GREEN, GREY, RED, YELLOW
from src.pipeline import Config, collect_bank, load_report_data, run

log = logging.getLogger(__name__)

LIGHT_ICON = {RED: "🔴", YELLOW: "🟡", GREEN: "🟢", GREY: "⚪"}

BANK_TITLES = {
    "psb": "ПСБ",
    "vtb": "ВТБ",
    "genbank": "ГенБанк",
    "cmr": "ЦМР",
    "sber": "Сбер",
}


def _config() -> Config:
    return Config.load()


def _esc(value: Any) -> str:
    return html.escape(str(value))


# --- сравнение -------------------------------------------------------------

def compare_text(bank_code: str) -> str:
    """Короткая сводка сравнения Сбера с одним банком."""
    config = _config()
    data = load_report_data(config, competitor=bank_code)

    title = BANK_TITLES.get(bank_code, bank_code)
    if data is None:
        return (f"<b>Сбер и {_esc(title)}</b>\n\n"
                "Данных пока нет. Нажми «Обновить данные» в меню.")

    counts = data["counts"]
    lines = [
        f"<b>Сбер и {_esc(title)}</b>",
        f"<i>Регион: {_esc(data['region'])} · сбор {_esc(data['collected_at'])}</i>",
        "",
        f"🔴 проигрываем {counts[RED]}   🟡 паритет {counts[YELLOW]}   "
        f"🟢 выигрываем {counts[GREEN]}   ⚪ нет данных {counts[GREY]}",
        "",
    ]

    counts_by_bank = data["product_counts"]
    rival_count = sum(counts_by_bank.get(t, 0) for t in data["competitor_titles"])
    home_count = counts_by_bank.get(data["home_title"], 0)

    comparisons = data["comparisons"]
    if not comparisons:
        # Различаем две разные причины пустого сравнения: нет данных
        # по банку и данные есть, но пары не сопоставлены.
        if rival_count == 0:
            lines.append(f"Данных по банку {_esc(title)} в последнем сборе нет.\n"
                         f"Собери их: «Обновить данные» → {_esc(title)}.")
        elif home_count == 0:
            lines.append("Данных по Сберу в последнем сборе нет — "
                         "собери их в меню «Обновить данные».")
        else:
            lines.append(f"Данные есть ({_esc(title)} — {rival_count}, "
                         f"Сбер — {home_count}), но пары продуктов "
                         "не сопоставлены.\n"
                         "Заполни config/product_map.yaml.")
    else:
        lines.append("<b>Продукты</b>")
        for c in comparisons[:12]:
            icon = LIGHT_ICON[c.light]
            prefix = "до" if c.rate_bound == "max" else "от"
            left = f"{prefix} {c.psb_rate:g}%" if c.psb_rate is not None else "—"
            right = f"{prefix} {c.sber_rate:g}%" if c.sber_rate is not None else "—"
            delta = f" ({c.delta_rate:+g} п.п.)" if c.delta_rate is not None else ""
            lines.append(f"{icon} <b>{_esc(c.label)}</b>\n"
                         f"      {_esc(title)} {left} · Сбер {right}{delta}")
        if len(comparisons) > 12:
            lines.append(f"<i>…и ещё {len(comparisons) - 12} — смотри в своде</i>")

    segments = [s for s in data["segments"] if s.verdict == "red"][:5]
    if segments:
        lines += ["", "<b>Где проигрываем по акциям</b>"]
        for s in segments:
            lines.append(f"🔴 {_esc(s.segment)}: {_esc(s.headline[:110])}")

    no_region = data.get("no_region") or []
    if no_region:
        names = ", ".join(no_region)
        lines += ["", f"⚠️ <i>Регион на сайте не выбран: {_esc(names)}. "
                      "Показаны условия, которые сайт отдал по умолчанию — "
                      "обычно московские, а не луганские.</i>"]

    if data["unverified"]:
        names = ", ".join(data["unverified"])
        lines += ["", f"⚠️ <i>Сбор не подтверждён на живых данных: {_esc(names)}. "
                      "Цифры по этим банкам сверь с первоисточником.</i>"]

    return "\n".join(lines)


# --- выгрузка --------------------------------------------------------------

def export_files(fmt: str) -> list[Path]:
    """Готовит файлы свода. fmt: xlsx | pdf | html | all."""
    from src.export import build_exports

    config = _config()
    data = load_report_data(config)
    if data is None:
        return []

    formats = ["xlsx", "pdf", "html"] if fmt == "all" else [fmt]
    return build_exports(config, data, formats)


# --- консультант -----------------------------------------------------------

def ai_answer(question: str) -> str:
    """Ответ AI-консультанта по собранным цифрам."""
    config = _config()
    data = load_report_data(config)
    if data is None:
        return ("Данных для совета пока нет — сначала обнови их в меню.")

    facts = consultant.build_facts(
        data["comparisons"], data["segments"], data["changes"],
        region=data["region"], banks=data["banks"],
    )

    try:
        advice = consultant.ask(facts, question)
    except consultant.ConsultantUnavailable as exc:
        return f"Консультант недоступен.\n{_esc(exc)}"

    log.info("Совет получен: %s", advice.usage_note)
    return advice.text


# --- сбор ------------------------------------------------------------------

def collect(bank_code: str) -> str:
    """Запускает сбор по одному банку или по всем."""
    config = _config()

    if bank_code == "all":
        result = run(config)
        counts = result["counts"]
        return (f"Сбор завершён.\n"
                f"Банков: {len(result['banks'])}, "
                f"продуктов: {result['products_total']}, "
                f"акций: {result['promos_total']}.\n"
                f"🔴 {counts[RED]}  🟡 {counts[YELLOW]}  "
                f"🟢 {counts[GREEN]}  ⚪ {counts[GREY]}")

    outcome = collect_bank(config, bank_code)
    return outcome.summary
