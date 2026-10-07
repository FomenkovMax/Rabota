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
from src.pipeline import Config, load_report_data

log = logging.getLogger(__name__)

LIGHT_ICON = {RED: "🔴", YELLOW: "🟡", GREEN: "🟢", GREY: "⚪"}

BANK_TITLES = {
    "psb": "ПСБ",
    "vtb": "ВТБ",
    "cmr": "ЦМР",
    "sber": "Сбер",
    "tbank": "Т-Банк",
    "rostfinance": "РостФинанс",
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

    federal = data.get("federal") or []
    if federal:
        lines += ["", f"ℹ️ <i>Единые условия по РФ: {_esc(', '.join(federal))}. "
                      "Отдельных условий для ЛНР на сайте банка нет.</i>"]

    if data["unverified"]:
        names = ", ".join(data["unverified"])
        lines += ["", f"⚠️ <i>Сбор не подтверждён на живых данных: {_esc(names)}. "
                      "Цифры по этим банкам сверь с первоисточником.</i>"]

    return "\n".join(lines)


# --- выгрузка --------------------------------------------------------------

def export_files(fmt: str) -> list[Path]:
    """Готовит файлы свода. fmt: xlsx | pdf | html | bi | all."""
    from src.export import ALL, build_exports

    config = _config()
    data = load_report_data(config)
    if data is None:
        return []

    formats = ALL if fmt == "all" else [fmt]
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

ROOT = Path(__file__).resolve().parent.parent


def collect_command(bank_code: str) -> list[str]:
    """Команда сбора отдельным процессом: все банки или один."""
    import sys

    command = [sys.executable, str(ROOT / "run.py"), "collect"]
    if bank_code != "all":
        command += ["--bank", bank_code]
    return command


def collect_summary(bank_code: str, returncode: int, tail: list[str]) -> str:
    """Сообщение по итогам сбора, который шёл отдельным процессом.

    Сбор вынесен из процесса бота: браузер ест много памяти, и когда
    7 октября системе её не хватило, вместе со сбором погиб и бот —
    сообщение «готово» так и не пришло. Теперь гибнет только сбор, а бот
    объясняет, что случилось.
    """
    if returncode < 0:
        return ("⚠️ Сбор прервался: процесс остановлен системой "
                f"(сигнал {-returncode}). Чаще всего так бывает, когда серверу "
                "не хватает памяти. Данные прошлых сборов на месте, выгрузка "
                "покажет их.")
    if returncode != 0:
        last = "\n".join(_esc(line) for line in tail[-5:])
        return f"⚠️ Сбор завершился с ошибкой (код {returncode}).\n<pre>{last}</pre>"

    data = load_report_data(_config())
    if data is None:
        return "Сбор завершён, но данных в базе нет — смотри лог сбора."
    banks = ", ".join(f"{bank} {n}" for bank, n in data["product_counts"].items())
    head = "Сбор завершён." if bank_code == "all" else "Банк обновлён."
    # Светофор считает только ручные пары, а их может не быть вовсе —
    # «🔴 0 🟡 0 🟢 0» читалось как «сравнивать нечего». Место Сбера на
    # рынке считается по всем банкам сразу.
    statuses: dict[str, int] = {}
    for gap in data.get("gaps") or []:
        statuses[gap.status] = statuses.get(gap.status, 0) + 1
    place = (f"🟢 лидер {statuses.get('лидер', 0)} · 🟡 в рынке {statuses.get('в рынке', 0)} · "
             f"🔴 отстаёт {statuses.get('отстаёт', 0)} · ⚪ не найдено у Сбера "
             f"{statuses.get('не найдено у Сбера', 0)}")
    manual = len(data.get("manual") or [])
    tail = f"\nНужна ручная проверка: {manual} знач." if manual else ""
    return (f"{head}\nПродуктов: {banks}.\n"
            f"Место Сбера по программам: {place}{tail}\n"
            "Подробно — в «📊 Выгрузить общий свод».")


# --- по категориям -----------------------------------------------------------

#: Код кнопки → категория продукта.
CATEGORIES = {
    "dep": "Вклады",
    "sav": "Накопительные счета",
    "loan": "Кредиты",
    "mtg": "Ипотека",
    "cc": "Кредитные карты",
}
GAP_ICON = {"лидер": "🟢", "в рынке": "🟡", "отстаёт": "🔴",
            "не найдено у Сбера": "⚪", "нет у конкурентов": "🔵", "нет данных": "▫️"}


def _rate(value: Any, better: str) -> str:
    if value is None:
        return "—"
    prefix = "до" if better == "higher" else "от"
    return f"{prefix} {value:g} %".replace(".", ",")


def _category_data(key: str) -> tuple[str, dict[str, Any] | None, list[Any], list[Any]]:
    category = CATEGORIES.get(key, "")
    data = load_report_data(_config())
    if data is None:
        return category, None, [], []
    gaps = [g for g in data.get("gaps") or [] if g.category == category]
    specials = [r for r in data.get("specials") or [] if r.category == category]
    return category, data, gaps, specials


def category_text(key: str) -> str:
    """Категория целиком: место Сбера по программам и особые условия."""
    category, data, gaps, specials = _category_data(key)
    if not category:
        return "Неизвестная категория."
    if data is None:
        return "Данных пока нет — сначала обнови их в меню."

    lines = [f"<b>{_esc(category)}</b>",
             f"<i>Сбор {_esc(data['collected_at'])} · сравниваются только базовые ставки</i>", ""]
    if not gaps:
        lines.append("Программ со ставками в этой категории нет.")
    for gap in gaps:
        icon = GAP_ICON.get(gap.status, "▫️")
        sber = _rate(gap.sber.value, gap.better) if gap.sber else "—"
        lines.append(f"{icon} <b>{_esc(gap.program)}</b> — {_esc(gap.status)}")
        lines.append(f"      Сбер {sber} · место {_esc(gap.place)}")
        top = [o for o in gap.offers if o.bank != data["home_title"]][:3]
        if top:
            lines.append("      " + " · ".join(
                f"{_esc(o.bank)} {_rate(o.value, gap.better)}" for o in top))
        if gap.comment and gap.status != "отстаёт":
            lines.append(f"      <i>{_esc(gap.comment[:140])}</i>")
    if specials:
        lines += ["", f"<b>Особые условия</b> ({len(specials)}) — в сравнение не идут:"]
        for row in specials[:8]:
            rate = "—" if row.rate is None else f"{row.rate:g} %".replace(".", ",")
            lines.append(f"• {_esc(row.bank)} · {_esc(row.title[:50])} — {rate} "
                         f"<i>({_esc(row.kind_label)})</i>")
        if len(specials) > 8:
            lines.append(f"<i>…и ещё {len(specials) - 8} — в своде, блок «Специальные условия»</i>")
    return "\n".join(lines)


def script_facts(key: str) -> tuple[str, str]:
    """Факты категории для скрипта: (категория, текст фактов)."""
    category, data, gaps, specials = _category_data(key)
    if data is None:
        return category, ""
    lines = [f"Категория: {category}. Регион: {data['region']}. Сбор: {data['collected_at']}."]
    for gap in gaps:
        sber = _rate(gap.sber.value, gap.better) if gap.sber else "нет данных"
        offers = "; ".join(f"{o.bank} — {o.title}: {_rate(o.value, gap.better)}"
                           for o in gap.offers)
        lines.append(f"Программа «{gap.program}»: статус {gap.status}, Сбер {sber}, "
                     f"место {gap.place}. Базовые ставки банков: {offers or 'нет'}.")
    for row in specials:
        rate = "—" if row.rate is None else f"{row.rate:g} %"
        lines.append(f"Особое условие: {row.bank} — {row.title}: {rate} "
                     f"({row.kind_label}; {row.reason}).")
    return category, "\n".join(lines)


def template_script(key: str) -> str:
    """Скрипт без модели: только утверждения, которые держатся на данных."""
    category, data, gaps, specials = _category_data(key)
    if data is None:
        return "Данных пока нет — сначала обнови их в меню."
    home = data["home_title"]
    lines = [f"<b>Аргументы для клиента: {_esc(category)}</b>",
             "<i>Собрано по данным сбора, без допущений. Перед разговором сверь условия "
             "по ссылке в своде.</i>", ""]
    welcome_by_bank: dict[str, list[Any]] = {}
    for row in specials:
        welcome_by_bank.setdefault(row.bank, []).append(row)
    said = 0
    for gap in gaps:
        if gap.sber is None:
            continue
        sber = _rate(gap.sber.value, gap.better)
        median = (_rate(gap.others_median, gap.better)
                  if gap.others_median is not None else "")
        if gap.status in ("лидер", "в рынке"):
            lines.append(f"• «{_esc(gap.program)}: у Сбера {sber}"
                         + (f", по рынку в среднем {median}" if median else "") + ".»")
            lines.append(f"   <i>(место {gap.place} среди {gap.banks_compared} банков, "
                         "базовые ставки)</i>")
            said += 1
        elif gap.status == "отстаёт" and gap.best is not None:
            best = gap.best
            lines.append(f"• «{_esc(gap.program)}: у {_esc(best.bank)} базовая ставка "
                         f"{_rate(best.value, gap.better)}, у Сбера {sber}.»")
            extra = welcome_by_bank.get(best.bank, [])
            if extra:
                kinds = ", ".join(sorted({r.kind_label for r in extra}))
                lines.append(f"   <i>(у {_esc(best.bank)} в категории есть ставки на особых "
                             f"условиях: {_esc(kinds)} — уточните, на какие условия смотрит "
                             "клиент)</i>")
            else:
                lines.append("   <i>(аргумента по ставке в данных нет — уточните условия у "
                             "продуктового блока)</i>")
            said += 1
        elif gap.status == "нет у конкурентов":
            lines.append(f"• «{_esc(gap.program)} — такой программы с опубликованной ставкой "
                         f"у других банков в регионе нет, у Сбера {sber}.»")
            said += 1
    rivals_special = [r for r in specials if r.bank != home]
    if rivals_special:
        lines.append("")
        lines.append("• Если клиент называет ставку конкурента выше нашей — проверьте, "
                     "не на особых ли она условиях:")
        for row in rivals_special[:5]:
            rate = "—" if row.rate is None else f"{row.rate:g} %".replace(".", ",")
            lines.append(f"   {_esc(row.bank)} · {_esc(row.title[:45])} {rate} — "
                         f"<i>{_esc(row.kind_label)}</i>")
        said += 1
    if not said:
        lines.append("По собранным данным аргументов нет: ставок Сбера в этой категории "
                     "на сайте не найдено. Уточните условия у продуктового блока.")
    return "\n".join(lines)


def client_script(key: str) -> str:
    """Скрипт для клиента: моделью по фактам, а без неё — по шаблону."""
    category, facts = script_facts(key)
    if not facts:
        return "Данных пока нет — сначала обнови их в меню."
    if consultant.available():
        try:
            advice = consultant.ask_script(facts)
            log.info("Скрипт получен: %s", advice.usage_note)
            return (f"<b>Аргументы для клиента: {_esc(category)}</b>\n"
                    "<i>Подготовлено AI только по собранным данным.</i>\n\n" + advice.text)
        except Exception as exc:                    # noqa: BLE001
            log.warning("Скрипт моделью не получился: %s — беру шаблон", exc)
    return template_script(key)


# --- автоаудит ---------------------------------------------------------------

def audit_command(llm: bool = False) -> list[str]:
    import sys

    command = [sys.executable, str(ROOT / "run.py"), "audit"]
    if llm:
        command.append("--llm")
    return command


def latest_audit_files() -> list[Path]:
    """Свежие отчёт и пакет автоаудита."""
    folder = _config().path("export", "audit_dir", default="data/audit")
    files = sorted(folder.glob("audit_*.html"))
    if not files:
        return []
    html_path = files[-1]
    zip_path = html_path.with_suffix(".zip")
    return [html_path] + ([zip_path] if zip_path.exists() else [])


def audit_summary(returncode: int, tail: list[str]) -> str:
    if returncode != 0:
        last = "\n".join(_esc(line) for line in tail[-5:])
        return f"⚠️ Аудит завершился с ошибкой (код {returncode}).\n<pre>{last}</pre>"
    keep = [line for line in tail if line.strip().startswith(("Автоаудит", "  "))]
    return "🧪 <b>Аудит готов</b>\n<pre>" + _esc("\n".join(keep[-12:])) + "</pre>"
