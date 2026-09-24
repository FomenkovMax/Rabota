"""Клавиатуры бота.

Меню ровно то, что заказано: выбор банка для сравнения со Сбером,
общий свод и AI-консультант. Один экран, без вложенных лабиринтов —
адресат открывает бота между делом и не будет искать нужную кнопку.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
    rows = [[InlineKeyboardButton(text=title, callback_data=f"cmp:{code}")]
            for code, title in COMPARE_TARGETS]
    rows.append([InlineKeyboardButton(text="Выгрузить общий свод",
                                      callback_data="export:menu")])
    rows.append([InlineKeyboardButton(text="AI-консультант",
                                      callback_data="ai:menu")])
    rows.append([InlineKeyboardButton(text="Обновить данные",
                                      callback_data="collect:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"export:{code}")]
            for code, title in EXPORT_FORMATS]
    rows.append([InlineKeyboardButton(text="Все форматы сразу",
                                      callback_data="export:all")])
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
    rows = [[InlineKeyboardButton(text=f"Только {title.split(' и ')[-1]}",
                                  callback_data=f"collect:{code}")]
            for code, title in COMPARE_TARGETS]
    rows.append([InlineKeyboardButton(text="Все банки",
                                      callback_data="collect:all")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В меню", callback_data="menu")]
    ])
