"""Клавиатуры бота.

Меню ровно то, что заказано: выбор банка для сравнения со Сбером,
общий свод и AI-консультант. Один экран, без вложенных лабиринтов —
адресат открывает бота между делом и не будет искать нужную кнопку.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Цвет кнопки — по смыслу действия. Telegram даёт три цвета; старые
# версии приложения их не показывают и рисуют кнопку обычной.
#   зелёный — обновить все банки, главное действие бота;
#   синий   — выгрузка готовых файлов;
#   без цвета — сравнения и всё остальное.
REFRESH = ButtonStyle.SUCCESS
COMPARE = None
EXPORT = ButtonStyle.PRIMARY


log = logging.getLogger(__name__)

# Значки из набора эмодзи Telegram вместо цвета. Файл лежит в config/,
# который смонтирован в контейнер: поменял id и перезапустил бота —
# пересобирать образ не нужно.
ICONS_FILE = Path(__file__).resolve().parent.parent / "config" / "bot_icons.yaml"
_icons_allowed = True


def _icons() -> dict[str, str]:
    if not _icons_allowed or not ICONS_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(ICONS_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:                        # noqa: BLE001
        log.warning("Не прочитан %s: %s", ICONS_FILE.name, exc)
        return {}
    return {str(key): str(value).strip() for key, value in data.items()
            if value and str(value).strip()}


def disable_icons(reason: str) -> None:
    """Telegram отказал в значках — дальше рисуем кнопки без них."""
    global _icons_allowed
    if _icons_allowed:
        log.warning("Значки на кнопках отключены: %s. Обычно причина в том, что "
                    "у владельца бота нет Telegram Premium.", reason)
    _icons_allowed = False


def icons_enabled() -> bool:
    return _icons_allowed


def button(key: str, emoji: str, text: str, callback: str,
           style: ButtonStyle | None = None) -> InlineKeyboardButton:
    """Кнопка со значком из набора, если он задан, иначе — с эмодзи и цветом.

    Значок заменяет и обычный эмодзи в начале подписи, и цвет: вместе они
    дублировали бы друг друга.
    """
    icon = _icons().get(key)
    if icon:
        return InlineKeyboardButton(text=text, callback_data=callback,
                                    icon_custom_emoji_id=icon)
    label = f"{emoji} {text}" if emoji else text
    return InlineKeyboardButton(text=label, callback_data=callback, style=style)


def strip_icons(markup: InlineKeyboardMarkup) -> None:
    """Убирает значки из уже собранной клавиатуры, возвращая цвет и эмодзи."""
    fallback = {"collect:all": ("🔄", REFRESH), "export:menu": ("📊", EXPORT),
                "ai:menu": ("🤖", None), "collect:menu": ("🔁", None)}
    for row in markup.inline_keyboard:
        for item in row:
            if not item.icon_custom_emoji_id:
                continue
            item.icon_custom_emoji_id = None
            emoji, style = fallback.get(item.callback_data or "", ("🏦", COMPARE))
            item.text = f"{emoji} {item.text}"
            item.style = style

# Код банка → подпись на кнопке. Порядок кнопок = порядок в этом списке.
COMPARE_TARGETS: list[tuple[str, str]] = [
    ("psb", "Сравнить Сбер и ПСБ"),
    ("vtb", "Сравнить Сбер и ВТБ"),
    ("genbank", "Сравнить Сбер и ГенБанк"),
    ("cmr", "Сравнить Сбер и ЦМР"),
]

EXPORT_FORMATS: list[tuple[str, str]] = [
    ("xlsx", "Excel"),
    ("pdf", "PDF"),
    ("html", "Дашборд HTML"),
    ("bi", "Данные для BI (CSV)"),
]


def main_menu() -> InlineKeyboardMarkup:
    rows = [[button("refresh_all", "🔄", "Обновить все банки", "collect:all", REFRESH)]]
    rows += [[button(f"compare_{code}", "🏦", title, f"cmp:{code}", COMPARE)]
             for code, title in COMPARE_TARGETS]
    rows.append([button("export", "📊", "Выгрузить общий свод", "export:menu", EXPORT)])
    rows.append([button("ai", "🤖", "AI-консультант", "ai:menu")])
    rows.append([button("refresh_one", "🔁", "Обновить один банк", "collect:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"export:{code}",
                                  style=EXPORT)]
            for code, title in EXPORT_FORMATS]
    rows.append([InlineKeyboardButton(text="Все форматы сразу",
                                      callback_data="export:all", style=EXPORT)])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_menu() -> InlineKeyboardMarkup:
    """Готовые вопросы — чтобы не печатать с телефона."""
    presets = [
        ("weak", "Где мы проигрываем сильнее всего"),
        ("promo", "Что делать с акциями"),
        ("week", "Что изменилось за неделю"),
    ]
    rows = [[InlineKeyboardButton(text=title, callback_data=f"ai:{code}")]
            for code, title in presets]
    rows.append([InlineKeyboardButton(text="Задать свой вопрос",
                                      callback_data="ai:free")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def collect_menu() -> InlineKeyboardMarkup:
    """Обновление одного банка. Все банки — отдельной кнопкой в главном меню."""
    rows = [[InlineKeyboardButton(text="Только Сбер", callback_data="collect:sber")]]
    rows += [[InlineKeyboardButton(text=f"Только {title.split(' и ')[-1]}",
                                   callback_data=f"collect:{code}")]
             for code, title in COMPARE_TARGETS]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
