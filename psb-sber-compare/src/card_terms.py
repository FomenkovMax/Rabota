"""Ключевые параметры карт — у них главное не ставка.

ТЗ просит сравнить все продукты розницы. У дебетовой карты клиент смотрит
на цену обслуживания, кешбэк и бесплатные переводы, у кредитной — ещё на
беспроцентный период. Здесь эти параметры вычитываются из описания карты
на странице банка (сбор 28.10.2026: Сбер, ВТБ, Т-Банк, РостФинанс).

Берётся только то, что прямо написано; не нашлось — параметра нет.
"""

from __future__ import annotations

import re
from typing import Any

SERVICE = "Обслуживание"
CASHBACK = "Кешбэк до"
CASHBACK_CAP = "Лимит кешбэка в месяц"
TRANSFERS = "Переводы без комиссии"
GRACE = "Беспроцентный период"
KEYS = (SERVICE, CASHBACK, CASHBACK_CAP, TRANSFERS, GRACE)

CARD_CATEGORIES = {"Дебетовые карты", "Кредитные карты", "Банковские карты",
                   "Пенсионные карты"}

_NUM = r"(\d[\d\s ]{0,9})"
_FREE = re.compile(r"(?:бесплатн\w*|0\s?₽\s+за)\s+(?:выпуск\w*\s+и\s+)?обслуживан|"
                   r"обслуживан\w*[^.\n]{0,30}\bбесплатн|выпуск,\s+обслуживание[^.\n]{0,30}"
                   r"|все\s+бесплатно", re.I)
_SERVICE_PRICE = re.compile(_NUM + r"\s?₽\s*(?:в|/)\s*мес", re.I)
# «до 10% бонусами/кешбэка/кэшбэка» — без партнёрских «суперкешбэк до 50%».
_CASHBACK = re.compile(r"(?<!супер)(?:до\s+)?(\d{1,2}(?:[,.]\d)?)\s?%\s+(?:кешб|кэшб|бонус|cashback)"
                       r"|(?<!супер)(?:кешб|кэшб)\w*\s+до\s+(\d{1,2}(?:[,.]\d)?)\s?%", re.I)
_CAP = re.compile(r"(?:максимальн\w+\s+сумм\w+\s+кешб|кешб\w*\s+до)[^\n]{0,30}?\s(?:—|-|–)?\s*"
                  + _NUM + r"\s?₽\s*(?:в\s+месяц)?", re.I)
_TRANSFERS = re.compile(r"(?:переводы?|по\s+сбп)[^.\n]{0,30}?без\s+комисси\w*\s+до\s+"
                        + _NUM + r"\s?₽|без\s+комисси\w*[^.\n]{0,20}до\s+" + _NUM
                        + r"\s?₽\s+в\s+месяц", re.I)
_GRACE = re.compile(r"(?:до\s+)?(\d{2,3})\s+дн\w*\s+без\s+(?:%|процент)", re.I)


def _int(text: str) -> int:
    return int(re.sub(r"\D", "", text))


def extract(lines: list[str]) -> dict[str, str]:
    """Параметры карты из строк описания: {параметр: значение}."""
    text = "\n".join(lines)
    out: dict[str, str] = {}

    if _FREE.search(text):
        out[SERVICE] = "бесплатно"
    else:
        for i, line in enumerate(lines):
            # «90 ₽ в месяц» рядом с подписью про обслуживание.
            near = " ".join(lines[max(0, i - 2): i + 3]).lower()
            match = _SERVICE_PRICE.search(line)
            # «при тратах от 1 000 000 ₽ в месяц — бесплатно» (Аэрофлот
            # Премиальная Сбера) — условие бесплатности, а не цена.
            if (match and "обслуживан" in near and "перевод" not in line.lower()
                    and not re.search(r"\bот\s+\d|трат|покуп|остат|оборот", line, re.I)
                    and _int(match.group(1)) <= 5000):
                out[SERVICE] = f"{_int(match.group(1))} ₽ в месяц"
                break

    values = []
    for match in _CASHBACK.finditer(text):
        raw = match.group(1) or match.group(2)
        value = float(raw.replace(",", "."))
        if 0 < value <= 30:
            values.append(value)
    if values:
        out[CASHBACK] = f"{max(values):g} %".replace(".", ",")

    cap = _CAP.search(text)
    if cap and _int(cap.group(1)) >= 100:
        out[CASHBACK_CAP] = f"{_int(cap.group(1)):,} ₽".replace(",", " ")

    transfers = _TRANSFERS.search(text)
    if transfers:
        amount = _int(transfers.group(1) or transfers.group(2))
        if 1000 <= amount <= 5_000_000:
            out[TRANSFERS] = f"до {amount:,} ₽ в месяц".replace(",", " ")

    grace = _GRACE.search(text)
    if grace:
        out[GRACE] = f"до {int(grace.group(1))} дней"
    return out


def summary(terms: dict[str, Any]) -> str:
    """Короткая строка для каталога: «обсл. бесплатно · кешбэк до 10 %»."""
    short = {SERVICE: "обсл.", CASHBACK: "кешбэк до", GRACE: "без % до",
             TRANSFERS: "переводы", CASHBACK_CAP: "лимит кешбэка"}
    parts = []
    for key in (SERVICE, CASHBACK, GRACE):
        value = str(terms.get(key) or "")
        if value:
            value = value.removeprefix("до ") if key == GRACE else value
            parts.append(f"{short[key]} {value}")
    return " · ".join(parts)
