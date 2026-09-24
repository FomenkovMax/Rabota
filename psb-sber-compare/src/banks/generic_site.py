"""Разбор условий с обычной страницы банка — по видимому тексту.

Для ПСБ мы разбираем структурированный JSON, и это лучший случай. У
остальных банков такого состояния нет: условия свёрстаны карточками, а
часть подгружается скриптами. Там приходится читать то же, что видит
человек, — отрендеренный текст.

Разбор по тексту заведомо грубее разбора по структуре, поэтому здесь
важно не делать вид, что точность та же. Модуль извлекает только то, что
однозначно читается: название продукта и ставку рядом с ним. Всё
сомнительное остаётся пустым, а не заполняется догадкой.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from ..psb.parser import Product, parse_money, parse_rates, parse_term_months

log = logging.getLogger(__name__)

_RATE_LINE = re.compile(r"(?:от|до|до\s+)?\s*\d{1,2}[,.]\d{1,2}\s?%")

# Процент на странице банка — далеко не всегда ставка. На карточке
# семейной ипотеки Сбера первой строкой идёт «Первоначальный взнос от
# 20,1%»: принятый за ставку, он переворачивает сравнение, потому что
# у ипотеки меньшая ставка лучше, а взнос к ставке отношения не имеет.
# Вырезается вместе с числом: от слова-признака до ближайшего процента.
# Класс [^%] не даёт захватить чужой процент, поэтому совпадение всегда
# обрывается на своём. Так строка «При взносе от 20,1% ставка 11,3%
# годовых» теряет взнос и сохраняет ставку, в каком бы порядке они ни
# стояли.
_NOT_A_RATE = re.compile(
    r"(?:первоначальн\w*\s+)?"
    r"(?:взнос\w*|комисси\w*|к[еэ]шб[еэ]к\w*|cashback|скидк\w*|страхов\w*|"
    r"ндфл|удержан\w*|дол[яию]\w*|долей|аванс\w*)"
    r"[^%]{0,40}?\d{1,3}(?:[,.]\d{1,2})?\s?%",
    re.I,
)
_PURE_RATE = re.compile(r"^\s*(?:от|до)?\s*\d{1,2}[,.]\d{1,2}\s?%\s*$", re.I)

# Строки, которые ставкой быть не могут, хотя процент в них есть.
_NOISE = re.compile(
    r"ключев\w*\s+ставк|минимальн\w*\s+гарантирован|инфляц|"
    r"комисси\w*\s+за|пеня|неустойк|штраф", re.I
)

# Слово, обозначающее продукт.
_PRODUCT_WORD = re.compile(
    r"вклад|кредит|карт|счет|счёт|ипотек|накопительн|депозит", re.I
)
# Кавычки в названии — сильный признак продукта: «ЦМР Старт», "Копилка".
_QUOTED = re.compile(r"[«\"\u201c\u2018][^»\"\u201d\u2019]{2,40}[»\"\u201d\u2019]")
# Строки-характеристики: слово продукта в них есть, а продуктом они не являются.
# «Ежемесячно на вклад» — это способ выплаты процентов из калькулятора,
# и без этой проверки он попадает в отчёт как название продукта.
_ATTRIBUTE_LINE = re.compile(
    r"^(ежемесячн|ежеквартальн|в\s+конце\s+срока|пополнение|снятие|"
    r"доходность|выплата|капитализац|процентная\s+ставка|ставка|срок|"
    r"сумма|валюта|минимальн|максимальн|доход\s+по|при\s+|для\s+|"
    r"на\s+имя|условия|способ)", re.I
)
_SERVICE_LINE = re.compile(
    r"^(главная|меню|контакты|документы|тариф|подробнее|оформить|"
    r"открыть|рассчитать|все |архив|©|версия)", re.I
)

# Заголовок раздела — не продукт. «Вклады и счета» содержит слово «вклад»
# и без этой проверки перехватывает ставку у первой карточки под ним,
# а неверная привязка ставки хуже, чем её отсутствие.
_SECTION_HEADING = re.compile(
    r"^(вклад(ы|у)?|кредит(ы|ование)?|карт(а|ы)|счет(а|ов)?|счёт(а|ов)?|"
    r"депозит(ы)?|ипотек(а|и)|накопительные\s+счета|дебетовые\s+карты|"
    r"кредитные\s+карты|банковские\s+карты|вклады\s+и\s+счета|"
    r"кредиты\s+и\s+карты|частным\s+клиентам|физическим\s+лицам)"
    r"\s*$", re.I
)


@dataclass
class TextProduct:
    """Продукт, вычитанный из текста страницы."""

    title: str
    rate_min: float | None = None
    rate_max: float | None = None
    rate_raw: str = ""
    context: str = ""


def _is_product_title(line: str) -> bool:
    if len(line) < 5 or len(line) > 90:
        return False
    if _SERVICE_LINE.match(line):
        return False
    if _PURE_RATE.match(line):
        return False
    if _SECTION_HEADING.match(line):
        return False
    if _ATTRIBUTE_LINE.match(line):
        return False

    # Название в кавычках — почти всегда продукт.
    if _QUOTED.search(line) and _PRODUCT_WORD.search(line):
        return True

    # Иначе слово продукта должно стоять в начале названия: «Вклад …»,
    # «Кредит наличными», «Дебетовая карта …». Если оно встретилось
    # в середине фразы, это, как правило, описание, а не заголовок.
    head = " ".join(line.split()[:2])
    return bool(_PRODUCT_WORD.search(head))


def extract_products(text: str, *, window: int = 6) -> list[TextProduct]:
    """Ищет пары «название продукта → ставка рядом».

    Окно в несколько строк — компромисс: в карточке название и ставка
    стоят рядом, но между ними бывают подписи вроде «Пополнение» и
    «Снятие». Брать ставку издалека нельзя: так она приклеится к чужому
    продукту, а неверная привязка хуже отсутствия данных.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    found: list[TextProduct] = []
    used_rate_lines: set[int] = set()

    for index, line in enumerate(lines):
        if not _is_product_title(line):
            continue

        for offset in range(1, window + 1):
            candidate_index = index + offset
            if candidate_index >= len(lines) or candidate_index in used_rate_lines:
                continue
            candidate = lines[candidate_index]
            if _NOISE.search(candidate):
                continue
            if not _RATE_LINE.search(candidate):
                continue

            # Строка вида «Ставка 12,5% годовых при взносе от 20,1%» несёт
            # оба процента сразу. Посторонние убираем вместе с их числами
            # и смотрим, осталась ли ставка: у карточки «Первоначальный
            # взнос от 20,1%» после этого не остаётся ничего, и продукт
            # честно уходит без ставки вместо выдуманной.
            measured = _NOT_A_RATE.sub(" ", candidate)
            if not _RATE_LINE.search(measured):
                continue

            rates = [r for r in parse_rates(measured) if 0.1 <= r <= 100]
            if not rates:
                continue

            used_rate_lines.add(candidate_index)
            context = " · ".join(lines[index:candidate_index + 2])[:300]
            found.append(TextProduct(
                title=line,
                rate_min=min(rates),
                rate_max=max(rates),
                rate_raw=candidate,
                context=context,
            ))
            break

    return found


def to_products(items: Iterable[TextProduct], *, bank: str, category: str,
                region: str, collected_at: str, source_url: str) -> list[Product]:
    """Переводит вычитанное в общую модель продукта."""
    out: list[Product] = []
    seen: set[str] = set()

    for item in items:
        key = item.title.lower()
        if key in seen:
            continue
        seen.add(key)

        product = Product(
            bank=bank,
            url_path=source_url,
            title=item.title,
            category=category,
            region=region,
            rate_min=item.rate_min,
            rate_max=item.rate_max,
            rate_raw=item.rate_raw,
            source_url=source_url,
            collected_at=collected_at,
        )
        if item.context:
            product.terms["Контекст на странице"] = item.context
        # Сумму и срок пробуем достать из того же контекста — но только
        # если они там есть явно.
        amounts = parse_money(item.context)
        if amounts:
            product.amount_min, product.amount_max = min(amounts), max(amounts)
            product.amount_raw = item.context[:200]
        months = parse_term_months(item.context)
        if months:
            product.term_min_months, product.term_max_months = min(months), max(months)
            product.term_raw = item.context[:200]

        out.append(product)

    return out
