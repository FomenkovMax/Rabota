"""Клавиатуры бота.

Меню ровно то, что заказано: выбор банка для сравнения со Сбером,
общий свод и AI-консультант. Один экран, без вложенных лабиринтов —
адресат открывает бота между делом и не будет искать нужную кнопку.
"""

from __future__ import annotations

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
]


def main_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔄 Обновить все банки",
                                  callback_data="collect:all", style=REFRESH)]]
    rows += [[InlineKeyboardButton(text=f"🏦 {title}", callback_data=f"cmp:{code}",
                                   style=COMPARE)]
             for code, title in COMPARE_TARGETS]
    rows.append([InlineKeyboardButton(text="📊 Выгрузить общий свод",
                                      callback_data="export:menu", style=EXPORT)])
    rows.append([InlineKeyboardButton(text="🤖 AI-консультант",
                                      callback_data="ai:menu")])
    rows.append([InlineKeyboardButton(text="🔁 Обновить один банк",
                                      callback_data="collect:menu")])
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
