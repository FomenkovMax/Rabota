"""Обход розницы банка по ссылкам: витрины → страницы продуктов.

Витрина показывает не всё. У Сбера на странице кредитов у карточек
«Кредит наличными», «Рефинансирование», «Автокредит» ставки нет — только
сумма и срок. Разбор, читавший одни витрины, такие продукты выбрасывал
целиком, и из восьми кредитов в отчёт попадал один.

Поэтому обход идёт по ссылкам: с витрин собираются адреса страниц
продуктов, каждая страница читается отдельно, условия берутся с неё.
Ставка, найденная на витрине, служит запасной: если страница продукта
цифры не показывает, берётся цифра с карточки — с пометкой, откуда она.

Продукт, у которого ставка на сайте не указана нигде, остаётся в данных
с этой пометкой. Отсутствие цифры — не повод терять сам продукт.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..psb.parser import Product, parse_money, parse_term_months
from .base import BankAdapter, CollectResult, region_binding
from .browser import (BrowserSettings, BrowserUnavailable, PageFailed,
                      PageReader, PageTooSlow)
from .generic_site import caption_rules_out, category_for, extract_products, rates_of
from .seo import is_seo_page
from .. import card_terms, conditions, coverage, market
from ..availability import find_clause

log = logging.getLogger(__name__)

# Где кончается описание продукта и начинаются чужие карточки, справка
# и подвал. Ставку ищем только выше этой черты: иначе к продукту без
# цифры в описании прилипла бы ставка соседнего продукта из подборки.
_STOP_LINE = re.compile(
    r"^(другие|ещё|еще|похожие|рекомендуем|вам (может|также)|полезн|"
    r"вопросы и ответы|часто задаваемые|остались вопросы|все вопросы|"
    r"документы|оцените|какой (вклад|кредит|карт)|смотрите также)",
    re.I,
)

# Меню вкладок под заголовком продукта: «Открыть онлайн · Рассчитать ·
# Подробные условия · Вопросы и ответы». «Вопросы и ответы» здесь — пункт
# меню, а не конец описания: если на нём остановиться, до таблицы ставок
# разбор не доходит, и у вклада со ставкой 13,5 % выходило «не указана».
_TAB = re.compile(
    r"^(открыть( вклад| сч[её]т)? онлайн|оформить( онлайн| карту)?|рассчитать|"
    r"подробные условия|где (открыть|оформить|получить)|как (оформить|вносить|"
    r"открыть|получить)|начисление процентов|проверить специальность|"
    r"изменить условия|подать заявку|спросить гигачат|условия|требования)$",
    re.I,
)

# Заглушка защиты Сбера вместо страницы. Текст ссылается на сертификаты,
# но приходит после десятков нормально прочитанных страниц — это защита
# от частых запросов. Обходить её нельзя; можно только сбавить темп.
_BLOCKED = re.compile(r"возникла проблема при открытии сайта|support id", re.I)


def is_blocked(data: dict[str, Any]) -> bool:
    return bool(_BLOCKED.search((data.get("text") or "")[:2000]))


# Заголовок страницы-раздела, а не продукта.
# Страницы, которые в каталоге рядом с продуктами, но продуктами не являются:
# услуги и функции («Ипотечные каникулы», «Управляйте списаниями…»),
# призывы («Открыть СберВклад онлайн») и заголовок-домен вместо названия.
_NOT_A_PRODUCT = re.compile(
    r"^(?:платите|управляйте|создайте|привез[её]м|покупайте|открыть|откройте|"
    r"оформите|узнайте|получите|переведите|подключите)\b|каникул|"
    r"программ\w*\s+поддержк|^[\w.-]+\.(?:ru|рф|com)$|^404|страница не найдена|"
    # Служебные страницы РостФинанса (обход 07.10.2026).
    r"способы\s+пополнения|страхование\s+вкладов|^выпуск\s+карты|соотношение|"
    r"^вклады\s+и\s+[сc]ч[её]та|^кредиты\s+наличными$|^кредитный\s+лимит|^вкладывайте|"
    # Заголовки витрин во множественном числе: «Дебетовые карты для
    # путешествий», «Банковские карты с кешбэком» — подборки, не продукты.
    r"^(?:банковские|дебетовые|кредитные)\s+карты\b|"
    # Подборки ВТБ во множественном числе: «Вклады в Самаре», «Вклады на
    # 1 год», «Накопительные счета до востребования», «Сберегательные вклады».
    r"^(?:вклады|накопительные\s+сч[её]та|сберегательные\s+вклады)\b|"
    # Драгметаллы и курсы — не розничные вклады и кредиты для сравнения.
    r"^курс\s|монет\w*\s+из\s+драгоцен|металлическ\w*\s+сч[её]т|^услуги\s+по\s+размещению",
    re.I,
)


def _shouting(title: str) -> bool:
    """Заголовок раздела заглавными буквами: «ВКЛАДЫ И CЧЕТА», «ИПОТЕКА»."""
    letters = [ch for ch in title if ch.isalpha()]
    return len(letters) > 4 and all(ch.isupper() for ch in letters)


def is_product_title(title: str) -> bool:
    return (bool(title) and not _GENERIC_TITLE.match(title)
            and not _NOT_A_PRODUCT.search(title) and not _shouting(title))


_GENERIC_TITLE = re.compile(
    r"^(все\s+)?(вклады( и сч[её]та)?|сч[её]та|кредиты|ипотек[аи]|карты|"
    r"кредитные карты|дебетовые карты|банковские карты|накопительные сч[её]та|"
    r"сбережения|частным клиентам)$",
    re.I,
)

_AMOUNT_PART = re.compile(
    r"^(от|до)?\s*\d[\d\s]*(?:[,.]\d+)?\s*(₽|руб|млн|млрд|тыс)", re.I)
_TERM_PART = re.compile(
    r"^(от|до|на)?\s*\d+\s*(лет|года|год|мес|дн|день|дня)", re.I)
# Подпись перед числом: «Сумма до 5 млн ₽», «Срок кредита: до 5 лет».
_LABEL = re.compile(
    r"^(сумма|срок|лимит|размер)(\s+(кредита|вклада|займа|лимита))?\s*:?\s*", re.I)
_PSK = re.compile(r"\bпск\b|полн\w*\s+стоимост", re.I)
_OWN_RATE = re.compile(r"\bставк\w*\b[^%]*\d", re.I)
_RANGE = re.compile(r"(\d{1,3}(?:[,.]\d{1,3})?)\s*[–—-]\s*(\d{1,3}(?:[,.]\d{1,3})?)\s*%")
# «Полная стоимость кредита — 2,950% — 3,000% годовых, ставка — 3% на весь
# срок» (образовательный кредит Т-Банка, 29.10.2026): ПСК и ставка в одной
# строке — делим, иначе ставка уходила в ПСК, а ставкой бралось 23,88 % из
# примера про господдержку ниже.
_PSK_THEN_RATE = re.compile(r"[,.;]\s+(?=(?:процентн\w+\s+)?ставк\w*\s*[—–:-]?\s*(?:от\s+|до\s+)?\d)",
                            re.I)
_FILE = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar)$", re.I)
_QUOTES = re.compile(r"[«»\"'„“”+]")


def normalize_title(title: str) -> str:
    """Ключ для сопоставления названий с витрины и со страницы продукта."""
    text = _QUOTES.sub(" ", title.replace("ё", "е").replace("Ё", "Е"))
    return " ".join(text.lower().split())


_IMPERATIVE = re.compile(r"^(?:оформите|откройте)\s+(.+)$", re.I)
_TITLE_TAIL = re.compile(r"\s+(?:со\s+ставкой|с\s+кэшбэком|получайте|онлайн\b|до\s+\d).*$", re.I)


# «ставкой» после прилагательного — часть названия: «Кредит с пониженной
# ставкой до 3%» (Сбер, 30.10.2026) — это «Кредит с пониженной ставкой».
_RATE_IN_TITLE = re.compile(
    r"(?:\s+доходност\w*|\s+со\s+ставк\w*|(?<!ой)(?<!ей)\s+ставк\w*)?\s+(?:до|от|со\s+ставкой)\s+\d[\d,.]*\s?%.*$",
    re.I)


def product_name(title: str) -> str:
    """Название продукта из рекламного заголовка.

    У Т-Банка заголовок страницы — призыв: «Оформите кредит наличными
    онлайн», «Откройте вклад со ставкой до 12,3% годовых». Продукт в нём
    есть, его и берём: «Кредит наличными», «Вклад».
    """
    match = _IMPERATIVE.match(title or "")
    if not match:
        # «ВТБ-Вклад в рублях до 13,7% годовых» → «ВТБ-Вклад в рублях»:
        # ставка в названии меняется, а название продукта — нет.
        return _RATE_IN_TITLE.sub("", title or "").strip() or title
    name = _TITLE_TAIL.sub("", match.group(1)).strip(" —-,")
    return name[:1].upper() + name[1:] if name else title


_NOT_FOUND = re.compile(r"такой страницы нет|такой страницы не существует|"
                        r"страница не найдена|page not found", re.I)
_SERVER_ERROR = re.compile(r"^\s*(?:404|50[0-4])\b|bad gateway|service unavailable", re.I)


def is_not_found(data: dict[str, Any]) -> bool:
    """Страница ошибки вместо продукта: 404 в оформлении сайта или 502 прокси."""
    head = (data.get("text") or "")[:3000]
    h1, title = (data.get("h1") or "").strip(), (data.get("title") or "").strip()
    return any(_SERVER_ERROR.search(t) or _NOT_FOUND.search(t) for t in (h1, title)) \
        or bool(_NOT_FOUND.search(head))


def clean_title(raw: str) -> str:
    """Заголовок страницы в одну строку, без хвостов вроде «— оформить онлайн»."""
    text = " ".join((raw or "").split())
    for separator in (" | ", " — ", " - "):
        if separator in text:
            text = text.split(separator)[0]
    return text.strip()


def _amount_and_term(lines: list[str]) -> dict[str, Any]:
    """Сумма и срок из первых строк описания.

    Строки вроде «От 30 000 ₽, от 1 месяца» разбираются по частям: целиком
    разборщик сроков принимал 30 000 за 30 000 месяцев. «до 5 млн» без
    знака рубля на карточке банка — тоже рубли.
    """
    found: dict[str, Any] = {}
    for line in lines[:15]:
        for part in (_LABEL.sub("", p.strip()) for p in line.split(",")):
            if "amount_raw" not in found and _AMOUNT_PART.match(part):
                money = part if re.search(r"₽|руб", part, re.I) else f"{part} ₽"
                values = parse_money(money)
                if values:
                    found.update(amount_raw=part, amount_min=min(values),
                                 amount_max=max(values))
            elif "term_raw" not in found and _TERM_PART.match(part):
                values = parse_term_months(part)
                if values:
                    found.update(term_raw=part, term_min_months=min(values),
                                 term_max_months=max(values))
        if "amount_raw" in found and "term_raw" in found:
            break
    return found


def _menu_item(line: str) -> bool:
    return len(line) <= 32 and not re.search(r"\d", line)


def describe_page(data: dict[str, Any]) -> tuple[str, list[str]]:
    """Название продукта и строки его описания — от заголовка до чужих карточек.

    Текст страницы начинается с меню сайта, поэтому описание отсчитывается
    от строки с заголовком. Если заголовок в тексте не нашёлся, описания
    нет вовсе: брать ставку откуда-то со страницы наугад нельзя.
    """
    title = clean_title(data.get("h1", "")) or clean_title(data.get("title", ""))
    lines = [line.strip() for line in (data.get("text") or "").split("\n")
             if line.strip()]
    if not title:
        return "", []

    head = [l.strip() for l in (data.get("h1") or title).split("\n") if l.strip()]
    first = normalize_title(head[0]) if head else normalize_title(title)
    start = -1
    for index, line in enumerate(lines):
        if normalize_title(line) == first:
            start = index
            break
    if start < 0 and not data.get("h1"):
        # Без H1 название берётся из заголовка окна, а он длиннее строки на
        # странице: «Кредит на образование с господдержкой» против «Кредит
        # на образование». Ищем строку, с которой заголовок начинается.
        for index, line in enumerate(lines):
            short = normalize_title(line)
            if len(short.split()) >= 2 and first.startswith(short):
                start, head = index, [line]
                break
    if start < 0:
        return title, []

    body: list[str] = []
    previous = ""
    rest = lines[start + len(head): start + len(head) + 150]
    for number, line in enumerate(rest):
        # Стоп-слово внутри меню вкладок — не конец описания. Меню видно по
        # виду: рядом две короткие строки без цифр — перед стоп-словом
        # («Шаги открытия вклада / Документы» у ВТБ) или после него
        # («Полезная информация / Условия / Ставки»). Если же рядом условия
        # с цифрами, это правда конец описания.
        in_menu = any(
            len(near) == 2 and all(_menu_item(l) for l in near)
            for near in (body[-2:], rest[number + 1: number + 3])
        )
        if _STOP_LINE.match(line) and not _TAB.match(previous) and not in_menu:
            break
        body.append(line)
        previous = line
    return title, body


_BONUS = re.compile(r"^\s*(?:до\s*)?\+\s?\d", re.I)


def _own_window(body: list[str], index: int, *, before: int = 12, after: int = 8) -> list[str]:
    """Строки вокруг ставки, которые относятся к ней, а не к соседней ставке.

    Таблица Сбера: «Ставка / От 20,4% / Получаю зарплату или пенсию в Сбере /
    … / Ставка / От 18,4%». Заголовок «Получаю зарплату» стоит под первой
    ставкой, но относится ко второй. Поэтому окно сверху обрывается на
    предыдущей ставке, а снизу — за несколько строк до следующей.
    """
    start = index
    while start > max(0, index - before):
        prev = body[start - 1]
        # ПСК над ставкой — часть того же блока таблицы: «Получаю зарплату /
        # Полная стоимость кредита / 18,400% – 48,200% / Ставка / От 18,4%».
        is_psk = bool(_PSK.search(prev)) or (start > 1 and bool(_PSK.search(body[start - 2])))
        if rates_of(prev) is not None and not is_psk:
            break
        start -= 1
    end = min(len(body), index + after + 1)
    # Новый раздел — уже не подписи к ставке: у рефинансирования Сбера под
    # общей ставкой 19,4 % идёт «Условия кредитования / … если получаете
    # зарплату…» (сбор 28.10.2026), и общая ставка читалась как зарплатная.
    end = next((i for i in range(index + 1, end)
                if _RATES_HEADING.match(body[i]) or _SECTION_END.match(body[i])), end)
    following = next((i for i in range(index + 1, end) if rates_of(body[i]) is not None), None)
    if following is not None:
        # Подписи над следующей ставкой — её, а не наши.
        end = max(index + 1, following - 6)
    return body[start:end]


def _rate_conditions(body: list[str], index: int, best: float) -> list[str]:
    """Условия ставки: рядом со строкой ставки и там, где та же цифра повторена.

    «До 14,2%» стоит в шапке, а «14,2% годовых — первые 2 месяца» — ниже,
    в описании (ВТБ-Счёт). Строка с той же цифрой и её соседи и есть
    расшифровка условий.
    """
    found = conditions.scan(" ".join(_own_window(body, index)))
    # Надбавки «До +3,3% годовых для новых вкладчиков» входят в «до 13,7%»:
    # максимальная ставка — это база плюс все надбавки.
    for position, line in enumerate(body):
        if _BONUS.match(line):
            found += conditions.near_rate(body, position, before=0, after=2)
    number = f"{best:g}".replace(".", ",")
    for position, line in enumerate(body):
        if position != index and re.search(rf"(?<![\d,]){re.escape(number)}(?:0*)\s?%", line):
            found += conditions.near_rate(body, position, before=1, after=1)
    return found


_FROM_RATE = re.compile(r"^\s*(?:ставка\s+)?от\s+\d", re.I)
_CLOSED = re.compile(
    # «Карты Visa/Mastercard сейчас не выпускаются» (Т-Банк, 29.10.2026).
    r"[^.\n]{0,60}(?:(?:больше|уже|сейчас|временно)\s+не\s+(?:выпуска|оформля|открыва|выда|принима)\w*|"
    r"прекращ\w+\s+(?:выпуск|оформлени|при[её]м|открыти)\w*|"
    # «Прием заявок завершен» (Сельская ипотека Сбера, 29.10.2026).
    r"при[её]м\s+заявок\s+(?:завершен|прекращ|приостановл)\w*|"
    r"не\s+доступ\w+\s+для\s+(?:оформления|открытия))[^.\n]{0,60}", re.I)
_RATE_CAPTION = re.compile(r"^\s*(?:процентная\s+|базовая\s+)?ставка\s*[:*\d]*\s*$", re.I)


def _is_condition(lines: list[str], i: int) -> bool:
    """«От 18,0 %» с подписью «Ставка» вплотную — условие продукта.

    Строки «от 0,5 %» у надбавок и скидок (Сбер) условием не считаются:
    подписи «Ставка» рядом с ними нет."""
    near = [lines[j] for j in (i - 1, i + 1) if 0 <= j < len(lines)]
    return (bool(_FROM_RATE.match(lines[i])) and rates_of(lines[i]) is not None
            and any(_RATE_CAPTION.match(n) for n in near))


def condition_block(lines: list[str]) -> list[str]:
    """Блок условий вокруг первой строки «от N % · Ставка» на всей странице:
    у ВТБ он ниже вкладок «Полезная информация», куда описание не доходит."""
    for i in range(len(lines)):
        if _is_condition(lines, i):
            return lines[max(0, i - 4): i + 4]
    return []

# Базовая ставка из юридической сноски: «ставка 9,6%-40,9% годовых с услугой
# «Максимум выгоды»(МВ). Без МВ … ставка 19,9%-55,4% годовых» (ВТБ, кредиты
# наличными, 28.10.2026). На витрине — ставка с платной услугой, а сравнивать
# по ТЗ нужно базовую.
_WITHOUT_SERVICE = re.compile(
    r"\bбез\s+(?:услуги\s+|подписки\s+)?(?:«[^»]{2,40}»|[А-ЯЁ]{2,4}\b|подписки|услуги)"
    r"[^.]{0,80}?\bставк\w*\s+(?:от\s+)?(\d{1,2}(?:[,.]\d{1,3})?)\s?%"
    r"(?:\s*[-–—]\s*(\d{1,2}(?:[,.]\d{1,3})?)\s?%)?", re.I)


def base_rate_without_service(product: Product, text: str) -> None:
    """Ставка с подпиской → базовая из сноски «без услуги … ставка N %»."""
    if conditions.kind_of(product)[0] != conditions.SUBSCRIPTION:
        return
    match = _WITHOUT_SERVICE.search(text or "")
    if not match:
        return
    low = float(match.group(1).replace(",", "."))
    high = float((match.group(2) or match.group(1)).replace(",", "."))
    if product.rate_min is not None and low <= product.rate_min:
        return
    product.terms["Ставка с платной услугой"] = (
        f"{product.rate_min:g} % — {product.rate_raw}".strip(" —"))
    product.terms.pop(conditions.TERMS_KEY, None)
    product.rate_min, product.rate_max = low, high
    product.rate_raw = " ".join(match.group(0).split())[:200]
    product.terms["Источник ставки на странице"] = "сноска: ставка без платной услуги"


# Ставки выше этого не бывает: «Ипотека на новостройку 79,9 %» в сборе
# 27.10.2026 — чужая цифра со страницы (доля, взнос), а не ставка.
# «Кредит под залог недвижимости 60 %» (28.10.2026) — тоже доля стоимости.
# Кредитные карты здесь не ограничиваем: у них 50–70 % — обычное дело.
_MAX_RATE = {"Ипотека": 40.0, "Кредиты": 50.0}
# В тарифе ставка прямо подписана «Процентная ставка», ПСК с ней не спутать:
# у кредитных карт Т-Банка (29.10.2026) — «от 29,9% до 61,9% годовых».
_TARIFF_MAX = {**_MAX_RATE, "Кредитные карты": 70.0}

# Категории, где ключевой параметр — ставка. Дебетовым картам и страховке
# ставка не нужна, их страницы в «Страницы без ставки» не идут.
_RATE_CATEGORIES = {"Вклады", "Накопительные счета", "Кредиты", "Ипотека",
                    "Кредитные карты"}
_CREDIT_CATEGORIES = {"Кредиты", "Ипотека", "Кредитные карты"}
_RATE_WORD = re.compile(r"годов|ставк|\bпск\b|полн\w*\s+стоимост|процентн", re.I)
_OTHER_PRODUCT = re.compile(r"накопительн\w*\s+сч[её]т|по\s+вклад|ставк\w*\s+по\s+вклад|на\s+остат", re.I)
_DEBIT_CATEGORIES = card_terms.CARD_CATEGORIES - {"Кредитные карты"}
# Процент у дебетовой карты — ставка только «на остаток»; кешбэк, скидки
# партнёров и «до 50 % баллами» ставкой не являются (сбор 29.10.2026:
# «Детская СберКарта — 11 %», «Карта болельщика ЦСКА — 50 %»).
_ON_BALANCE = re.compile(r"на\s+остат|остаток|на\s+(?:сво[йи]|минимальн\w*)\s+остат|"
                         r"доход\w*\s+на\s+(?:остат|деньги)|процент\w*\s+на\s+(?:остат|сумм)", re.I)
_CASHBACK_WORD = re.compile(r"кешб|кэшб|cashback|бонус|балл|скидк|милл|мил[еь]", re.I)


def _keep_balance_rate(product: Product, body: list[str]) -> None:
    """У дебетовой карты оставляет только процент на остаток — или ничего."""
    if product.rate_min is None:
        return
    for i, line in enumerate(body):
        if not _ON_BALANCE.search(line):
            continue
        for near in (line, *body[i + 1:i + 2], *body[max(0, i - 1):i]):
            values = rates_of(near)
            if values and not _CASHBACK_WORD.search(near):
                product.rate_min, product.rate_max = min(values), max(values)
                product.rate_raw = near
                product.terms["Ставка"] = "процент на остаток по карте"
                return
    product.terms["Процент в описании карты"] = (
        f"{product.rate_raw or product.rate_min} — не ставка на остаток (кешбэк, бонусы "
        "или скидка), в ставки не идёт")[:200]
    product.rate_min = product.rate_max = None
    product.rate_raw = ""


def _found(product: Product | None) -> str:
    """Что разбор взял со страницы — для заголовка сохранённого текста."""
    if product is None or (product.rate_min is None and product.apr_min is None):
        return "ставка не найдена"
    rate = (f"ставка {product.rate_min:g}–{product.rate_max:g}"
            if product.rate_min is not None else "ставки нет")
    kind, reason = conditions.kind_of(product)
    return f"{rate}; {reason or conditions.LABELS[kind]}"


#: Ставка, выведенная из платежа калькулятора (оценка, в рейтинг не идёт).
IMPLIED_KEY = "Ставка по платежу калькулятора"

#: Служебные строки охвата: полнота обхода сайта банка.
CRAWL_READ_KEY = "Обход: прочитано страниц"
CRAWL_SITEMAP_KEY = "Обход: страниц в карте сайта"
CRAWL_UNREAD_KEY = "Обход: не прочитаны"
CRAWL_FAILED_KEY = "Обход: ошибки чтения"
# Витрины разделов — не продукты: в «не прочитаны» не попадают.
_LISTING = re.compile(r"/(?:deposits|money|home|homenew|credit_cards|debit|bank_cards|"
                      r"credits|contributions|ipoteka|kredit|karty|vklady-i-scheta)/?$", re.I)

#: Служебные строки охвата: страница офисов и что на ней про Луганск.
OFFICES_KEY = "Офисы в ЛНР"
OFFICES_PROOF_KEY = "Офисы в ЛНР: подтверждение"

_OFFICE_TEXT = re.compile(
    r"^(?:офисы(?:\s+и\s+банкоматы)?|отделения(?:\s+и\s+банкоматы)?|"
    r"банкоматы\s+и\s+(?:офисы|отделения)|адреса(?:\s+офисов)?|где\s+нас\s+найти|"
    r"офисы\s+обслуживания)$", re.I)
_LUGANSK = re.compile(r"[^\n]{0,80}\bЛуганск\w*[^\n]{0,120}", re.I)
_ADDRESS = re.compile(r"\bул\.|улиц|просп|пр-т|пл\.|площад|кв-л|квартал|\bд\.\s?\d|"
                      r"\d{2,}[,\s]|часы\s+работы|режим\s+работы", re.I)


def office_link(links: list[Any], base_url: str) -> str:
    """Ссылка «Офисы и банкоматы» из меню или подвала сайта банка."""
    own = urlsplit(base_url).netloc.removeprefix("www.")
    for item in links:
        if isinstance(item, (list, tuple)):
            href, text = (str(item[0]) if item else ""), (str(item[1]) if len(item) > 1 else "")
        else:
            href, text = str(item), ""
        if not text or not _OFFICE_TEXT.match(text.strip()):
            continue
        if own and own in urlsplit(href).netloc:
            return href
    return ""


def lugansk_quote(text: str) -> str:
    """Цитата со страницы офисов: Луганск рядом с адресом или часами работы.

    Одно слово «Луганск» в списке городов — ещё не офис: нужна строка
    с признаком адреса. Нет такой — пусто."""
    for match in _LUGANSK.finditer(text or ""):
        line = " ".join(match.group(0).split())
        if _ADDRESS.search(line):
            return line[:200]
    return ""


def market_program(product: Product) -> str:
    """Программа пункта калькулятора — только если она распознана по названию.

    «Квартира на вторичном рынке» → «Вторичное жильё». Пункт без явной
    программы (уходит в «Рыночную ипотеку» по умолчанию) не помечаем: иначе
    недоступность одного пункта закрыла бы всю рыночную ипотеку.
    """
    from .. import market
    program = market.program_of(product)
    return "" if program in market._DEFAULT_PROGRAM.values() else program


def mark_blocked(products: list[Product], blocked: dict[str, str]) -> None:
    """Продукты программ, которые калькулятор назвал недоступными в регионе."""
    if not blocked:
        return
    from .. import market
    for product in products:
        note = blocked.get(market.program_of(product))
        if note and product.category in ("Ипотека", "Кредиты"):
            product.terms.setdefault(market.REGION_KEY, note)


def _worth_saving(product: Product) -> bool:
    """Страницу стоит сохранить для доработки разбора.

    Ставка не найдена — или у кредита она найдена, но на особых условиях:
    рефинансирование Сбера 27.10.2026 вышло «17,4 % для зарплатных», а
    общая ставка 19,4 % на той же странице. Без текста страницы не видно,
    почему разбор её пропустил.
    """
    if product.category not in _RATE_CATEGORIES:
        return False
    if product.rate_min is None and product.apr_min is None:
        return True
    if product.category not in _CREDIT_CATEGORIES:
        return False
    # Подозрительные цифры — проверка отчёта их отсеет, а без текста страницы
    # не понять, почему: ипотека Сбера 28.10.2026 — «ставка 18,7 %, ПСК 18,01 %»,
    # кредитная СберКарта — «10 %».
    rate, apr = product.rate_min, product.apr_min
    if rate is not None and apr is not None and apr < rate:
        return True
    if rate is not None and rate < 12 and product.category != "Ипотека":
        return True
    return not conditions.is_comparable(product)


def _split_psk_and_rate(body: list[str]) -> list[str]:
    out: list[str] = []
    for line in body:
        match = _PSK_THEN_RATE.search(line) if _PSK.search(line) else None
        if match and _PSK.search(line[:match.start()]):
            out += [line[:match.start()].strip(), line[match.end():].strip()]
        else:
            out.append(line)
    return out


def _read_rates(product: Product, body: list[str]) -> None:
    """Ставка и ПСК из строк описания — первая базовая ставка.

    Таблица условий бывает из нескольких блоков: у Сбера на живой странице
    (07.10.2026) «Получаю зарплату или пенсию — от 18,4 %» стоит ВЫШЕ
    «Общих условий — от 20,4 %». Если у первой ставки в её собственном
    окне сказано про особые условия, ищем дальше такую же строку таблицы
    (с той же подписью «Ставка») без особых условий. Не нашли — берём первую.
    """
    fallback: tuple[list[float], str, int, tuple] | None = None
    block_apr: list[float] = []          # ПСК текущего блока таблицы
    ceiling = _MAX_RATE.get(product.category)
    # У кредитов условие пишется «от N %». Если на странице такое есть, голые
    # «20,4 %» — это расчёт калькулятора по умолчанию (ВТБ, ипотека на
    # новостройку 28.10.2026: расчёт «ПСК 19,144–25,907 % / Ставка 20,4 %»
    # выше условий «От 18,0 % · Ставка»), их не берём.
    def is_condition(i: int) -> bool:
        return _is_condition(body, i)
    body = _split_psk_and_rate(body)
    from_only = product.category in _CREDIT_CATEGORIES and any(
        is_condition(i) for i in range(len(body)))
    for index, line in enumerate(body):
        values = rates_of(line)
        if values is None:
            continue
        # На странице кредитки — реклама соседних продуктов: «9% годовых по
        # накопительному счету» (S7 Premium Т-Банка, 29.10.2026).
        if product.category in _CREDIT_CATEGORIES and _OTHER_PRODUCT.search(line):
            continue
        # Вёрстка ВТБ дублирует цифру для мобильной и полной версии:
        # «от 19.144 до 23.705%» и сразу «19,144-23,705%». Второй экземпляр
        # с подписью «Ставка» под ним читался ставкой — пропускаем дубль.
        prev_values = rates_of(body[index - 1]) if index > 0 else None
        if prev_values and sorted(prev_values) == sorted(values):
            continue
        following = body[index + 1] if index + 1 < len(body) else ""
        # «от 20,1%» с подписью «первоначальный взнос» — не ставка. Подпись
        # бывает и над числом: «Начисление бонусов по программе / до 1% / годовых».
        # Подпись сверху — только если она не подпись к числу перед ней:
        # «от 20,1% / Первоначальный взнос / от 6%» — взнос относится к 20,1.
        previous = body[index - 1] if index > 0 else ""
        before = body[index - 2] if index > 1 else ""
        caption_above = caption_rules_out(previous) and rates_of(before) is None
        if caption_rules_out(following) or caption_above:
            continue
        # ПСК — полная стоимость кредита, а не ставка. Кладём её в своё
        # поле: в светофоре ставка сравнивается со ставкой, не с ПСК.
        # Таблица «подписи сверху, значения снизу» (ВТБ): «Диапазон полной
        # стоимости кредита / Ставка / На весь срок / 18,662 – 25,643% /
        # от 2%». Первое число после подписи ПСК — это ПСК, не ставка.
        # Подписи сверху ищем только до предыдущего числа: у «от 2%» под
        # «18,662 – 25,643%» подпись ПСК относится к числу выше.
        above = []
        for near in reversed(body[max(0, index - 3):index]):
            if rates_of(near) is not None:
                break
            above.append(near)
        psk_above = bool(_PSK.search(" ".join(above)))
        # Одна подпись между двумя числами без двоеточия — подпись снизу к
        # числу выше: «19,900% – 55,400% / Полная стоимость кредита /
        # От 9,6% / Ставка» (ВТБ). «…полной стоимости кредита: / 24,999%» —
        # подпись сверху, к числу ниже.
        if (len(above) == 1 and index > 1 and rates_of(body[index - 2]) is not None
                and not above[0].rstrip().endswith(":")):
            psk_above = False
        # «Полная стоимость кредита / До 30 лет / Срок кредита / От 18,0% /
        # Ставка» (ВТБ): подпись «Ставка» прямо под числом сильнее подписи
        # ПСК тремя строками выше — та относится к числу над ней.
        # У Сбера подписи над числом («Полная стоимость кредита / 18,014% —
        # 24,812% / Базовая ставка / 18,7%»): там подпись ПСК прямо сверху —
        # она и решает.
        if _RATE_CAPTION.match(following) and not _PSK.search(previous):
            psk_above = False
        # «СТАВКА ПО КРЕДИТУ: 22,5% ГОДОВЫХ» — подпись в самой строке, и
        # подпись ПСК под ней («Минимальный размер полной стоимости
        # кредита:») относится уже к следующему числу.
        own_rate = bool(_OWN_RATE.search(line)) and not _PSK.search(line)
        if not own_rate and (_PSK.search(line) or _PSK.search(following) or psk_above):
            # «18,662 – 25,643%»: знак процента только у второго числа.
            span = _RANGE.search(line)
            if span:
                values = [float(span.group(1).replace(",", ".")),
                          float(span.group(2).replace(",", "."))]
            block_apr = list(values)
            if product.apr_min is not None and fallback is None:
                values += [product.apr_min, product.apr_max]
            if fallback is None:
                product.apr_min, product.apr_max = min(values), max(values)
                product.apr_raw = f"{line} {following}".strip()
            continue
        # У кредитки ставка всегда подписана «годовых» или «ставка».
        # Без этих слов рядом — кешбэк: «2% в супермаркетах, кафе»,
        # «До 10% за покупки на АЗС», «до 50% / за покупки у партнеров»
        # (Т-Банк, ВТБ, 29.10.2026).
        if product.category == "Кредитные карты" and not _RATE_WORD.search(
                " ".join(body[max(0, index - 1):index + 2])):
            continue
        # «29,9 — 61,9% годовых» (кредитки Т-Банка, 29.10.2026): знак процента
        # только у второго числа — нижняя граница терялась.
        span = _RANGE.search(line)
        if span and len(values) == 1 and float(span.group(2).replace(",", ".")) == values[0]:
            values = [float(span.group(1).replace(",", ".")), values[0]]
        # Ставка выше порога — доля или взнос, а не ставка (ПСК выше уже
        # разобрана: у неё 50 % с лишним бывает законно).
        if ceiling is not None and max(values) > ceiling:
            continue
        if from_only and not own_rate and not is_condition(index):
            continue
        caption = body[index - 1] if index > 0 else ""
        own = conditions.scan(" ".join(_own_window(body, index)))
        if fallback is None and own:
            # Особые условия у первой ставки — посмотрим, есть ли общая.
            fallback = (values, line, index, tuple(block_apr))
            block_apr = []
            continue
        if fallback is not None:
            if own or caption != (body[fallback[2] - 1] if fallback[2] > 0 else ""):
                block_apr = []
                continue
            if block_apr:
                product.apr_min, product.apr_max = min(block_apr), max(block_apr)
        product.rate_min, product.rate_max = min(values), max(values)
        product.rate_raw = line
        conditions.remember(product, _rate_conditions(body, index, max(values)))
        return

    if fallback is not None:
        values, line, index, apr = fallback
        product.rate_min, product.rate_max = min(values), max(values)
        product.rate_raw = line
        conditions.remember(product, _rate_conditions(body, index, max(values)))


_RATES_HEADING = re.compile(
    r"^(?:ставки по (?:кредиту|ипотеке|вкладу)|ставки рефинансирования|"
    r"ставки и условия|условия и ставки|"
    r"процентные ставки|подробные условия|условия кредит\w*)$", re.I)
_SECTION_END = re.compile(
    r"^(?:требования к заё?е?мщик|документы|документы и ссылки|"
    r"вопросы и ответы|юридическая информация|оцените)", re.I)


def rates_section(data: dict[str, Any]) -> list[str]:
    """Блок «Ставки по кредиту» в любом месте страницы.

    У Сбера ставки — во вкладке «Подробные условия» внизу длинной страницы
    (ручная проверка 07.10.2026): от заголовка продукта до неё больше
    150 строк. Берём блок под заголовком, за которым в ближайших строках
    есть ставка; подпись вкладки в меню («Подробные условия» без цифр
    рядом) пропускается.
    """
    lines = [l.strip() for l in (data.get("text") or "").split("\n") if l.strip()]
    for index, line in enumerate(lines):
        if not _RATES_HEADING.match(line):
            continue
        block = []
        for item in lines[index + 1:index + 80]:
            if _SECTION_END.match(item):
                break
            block.append(item)
        if any(rates_of(item) is not None for item in block[:25]):
            return block
    return []


def product_from_page(data: dict[str, Any], *, bank: str, url: str,
                      category: str, region: str, collected_at: str) -> Product | None:
    """Продукт со страницы продукта. None — если это не страница продукта."""
    title, body = describe_page(data)
    headline = title
    title = product_name(title)
    if not is_product_title(title):
        return None

    product = Product(
        bank=bank, url_path=urlsplit(url).path, title=title,
        category=category_for(title, category), region=region,
        source_url=url, collected_at=collected_at,
    )

    rate_lines = body
    # Цифры в описании есть, а условия «от N % · Ставка» нет — это расчёт
    # калькулятора (ВТБ), условие ищем по всей странице. Цифр нет вовсе —
    # работает поиск блока «Ставки по кредиту» ниже (Сбер).
    if (product.category in _CREDIT_CATEGORIES
            and any(rates_of(line) is not None for line in body)
            and not any(_is_condition(body, i) for i in range(len(body)))):
        page_lines = [l.strip() for l in (data.get("text") or "").split("\n") if l.strip()]
        extra = condition_block(page_lines)
        if extra:
            rate_lines = body + extra
    _read_rates(product, rate_lines)

    # Ставки в описании нет, но она есть в самом заголовке страницы
    # продукта: «ВТБ-Вклад в рублях до 13,7% годовых».
    if product.rate_min is None and headline != title:
        values = rates_of(headline)
        if values:
            conditions.remember(product, conditions.scan(headline)
                                + _rate_conditions(body, 0, max(values)))
            product.rate_min, product.rate_max = min(values), max(values)
            product.rate_raw = headline

    # Ставка ниже по странице — во вкладке «Ставки по кредиту» (Сбер).
    if product.rate_min is None:
        block = rates_section(data)
        if block:
            _read_rates(product, block)
            if product.rate_min is not None:
                product.terms["Источник ставки на странице"] = "блок «Ставки по кредиту»"

    for key, value in _amount_and_term(body).items():
        setattr(product, key, value)

    if product.category in _DEBIT_CATEGORIES:
        _keep_balance_rate(product, body)

    if product.rate_min is None:
        product.terms["Ставка"] = ("на странице указана только ПСК"
                                   if product.apr_min is not None
                                   else "на странице продукта не указана")
    if body:
        product.terms["Контекст на странице"] = " · ".join(body[:8])[:300]
    base_rate_without_service(product, data.get("text") or "")
    # «Карта больше не выпускается», «приём заявок прекращён» — продукт есть
    # на сайте, но оформить его нельзя: в сравнение не идёт.
    # Оговорка бывает прямо в заголовке страницы — его тоже смотрим.
    closed = _CLOSED.search("\n".join([product.title or "", *body[:40]]))
    if closed:
        product.terms[conditions.CLOSED_KEY] = " ".join(closed.group(0).split())[:160]
    # Карты: обслуживание, кешбэк, переводы, беспроцентный период — из
    # описания карты (не из меню и подвала).
    if product.category in card_terms.CARD_CATEGORIES:
        for key, value in card_terms.extract(body).items():
            product.terms.setdefault(key, value)
    # Ставка — результат калькулятора на странице с его настройками по
    # умолчанию (ВТБ: «Расчёт произведён … Ставка 20,4 %»), а условия «от N %»
    # на странице нет. Сравнивать можно, но с пометкой.
    if (product.rate_min is not None and product.category in _CREDIT_CATEGORIES
            and not _FROM_RATE.match(product.rate_raw or "")
            and not any(_is_condition(rate_lines, i) for i in range(len(rate_lines)))
            and re.search(r"расч[её]т\s+произвед", data.get("text") or "", re.I)):
        product.terms["Источник ставки на странице"] = (
            "расчёт калькулятора на странице с настройками по умолчанию")
    # «Субсидирование процентной ставки учитывалось» — ПСК посчитана с
    # субсидией застройщика и законно ниже базовой ставки (ипотека Сбера:
    # базовая 18,7 %, ПСК от 18,014 %, сбор 28.10.2026).
    if re.search(r"субсидир\w*[^.]{0,60}?учитыва", data.get("text") or "", re.I):
        product.terms[market.PSK_SUBSIDY_KEY] = (
            "ПСК рассчитана с учётом субсидирования ставки — так сказано на странице")
    # Оговорка о регионе в описании продукта: «не предоставляется в ДНР, ЛНР…».
    # Только описание и блок ставок — в меню и подвале сайта таких фраз
    # хватает, и к продукту они не относятся.
    clause = find_clause("\n".join(body + rates_section(data)))
    if clause:
        product.terms.setdefault(market.REGION_KEY, f"на странице банка: «{clause}»")
    return product


class CrawlAdapter(BankAdapter):
    """Базовый адаптер для банков, чей каталог обходится по ссылкам."""

    #: Сайт банка: только его ссылки идут в обход.
    base_url: str = ""
    #: Страницы-витрины, с которых начинается обход.
    seeds: tuple[str, ...] = ()
    #: Главные продукты — читаются сразу после витрин. Сайт пускает
    #: ограниченное число страниц за сеанс, и они должны уйти на то, что
    #: важно для сравнения, а не на подстраницы.
    priority: tuple[str, ...] = ()
    #: Разделы розницы: (префикс пути, категория по умолчанию). Порядок
    #: важен — более точный префикс идёт раньше общего.
    families: tuple[tuple[str, str], ...] = ()
    #: Раздел по словам в адресе — для сайтов, чью структуру мы ещё не
    #: видели: (регулярка по пути, категория). Проверяются после families.
    family_words: tuple[tuple[str, str], ...] = ()
    #: Не отрезать «/» в конце адреса: у части сайтов (РостФинанс) адрес без
    #: неё — это страница 404.
    keep_slash: bool = False
    #: Служебные страницы внутри разделов: справка, калькуляторы, архивы.
    skip: re.Pattern[str] = re.compile(r"$^")
    protection: str = ""
    wait_for: str = ""
    sets_region: bool = False

    def collect(self) -> CollectResult:
        if not self.seeds or not (self.families or self.family_words):
            return self._failed("не заданы витрины и разделы для обхода")

        settings = BrowserSettings.from_config(self.settings.get("browser"))
        # Своя пауза между страницами для банка, чья защита не любит частых
        # запросов, — поверх общей настройки браузера.
        if self.settings.get("pause_s"):
            settings.pause_s = float(self.settings["pause_s"])
        # Калькуляторы: регион ЛНР, все цели из списка — на страницах, адрес
        # которых подходит под calculator_paths (иначе на каждой витрине
        # агент искал бы калькулятор впустую).
        if self.settings.get("calculator_paths"):
            settings.calculator_region = str(
                self.settings.get("calculator_region")
                or "Луганская Народная Республика, Луганск")
            settings.calculator_paths = str(self.settings["calculator_paths"])
            settings.record_network = True
        now = datetime.now().isoformat(timespec="seconds")
        region_cookies = self.settings.get("region_cookies") or []
        method, region_label = region_binding(self.sets_region, self.settings)
        applied = method != "not_confirmed"
        if method == "not_confirmed":
            log.warning("%s: регион на сайте не задан — условия будут те, что сайт "
                        "отдаёт по адресу сервера. Настроить: banks.%s.region_cookies, "
                        "а если про ЛНР на сайте ничего нет — banks.%s.region_mode: federal",
                        self.title, self.code, self.code)

        max_pages = int(self.settings.get("max_pages") or 80)
        limit_s = float(self.settings.get("section_timeout_s") or 0)

        seeds = [self._normalize(url) for url in self.seeds]
        seed_set = set(seeds)
        first = [self._normalize(url) for url in self.priority]
        first_set = set(first)
        queue: deque[str] = deque(seeds + [u for u in first if u not in seed_set])
        seen: set[str] = set(queue)

        products: dict[str, Product] = {}
        showcase: dict[str, tuple[Any, str, str]] = {}
        failures: list[str] = []
        visited = 0
        self._clear_missing()
        calc_blocked: dict[str, str] = {}      # программа → что сказал калькулятор
        sitemap_found: set[str] = set()         # страницы из карты сайта
        office_url = ""                         # страница «Офисы и банкоматы»
        site_sections: dict[str, str] = {}
        retried: set[str] = set()
        blocked = False
        # Сколько прочитанных страниц ссылается на адрес. Основные продукты
        # стоят в меню каждой страницы, рекламные дубли («кредит на 50 000
        # рублей», «кредитка в Курске») — на одной. Лимит страниц и терпение
        # защиты конечны, поэтому сначала читаем самое упоминаемое.
        popularity: dict[str, int] = {url: 500_000 for url in first}
        popularity.update({url: 1_000_000 for url in seeds})
        started = time.monotonic()

        try:
            with PageReader(settings, cookies=region_cookies or None,
                            wait_for=self.wait_for, limit_s=limit_s) as reader:
                # Карта сайта — все страницы розницы, а не только те, на
                # которые есть ссылки с витрин: так видно, что существует,
                # даже если до страницы не дошли.
                for url in self._sitemap_urls(reader):
                    if url not in seen:
                        seen.add(url)
                        queue.append(url)
                        sitemap_found.add(url)
                while queue and visited < max_pages:
                    url = self._next(queue, popularity)
                    visited += 1
                    log.info("%s: страница %s (в очереди %s) — %s",
                             self.title, visited, len(queue), urlsplit(url).path)
                    try:
                        data = reader.read(url)
                        if is_blocked(data):
                            data = self._after_block(reader, url)
                    except (PageTooSlow, PageFailed) as exc:
                        log.warning("%s: страница не прочиталась — %s",
                                    self.title, str(exc)[:160])
                        # Первая страница у Сбера долгая: защита проверяет
                        # свежий браузер. Витрину не теряем — ещё одна
                        # попытка позже, когда браузер уже прогрет.
                        if url in seed_set and url not in retried:
                            retried.add(url)
                            popularity[url] = -1
                            queue.append(url)
                            visited -= 1
                            continue
                        failures.append(f"{url}: {str(exc)[:80]}")
                        continue
                    if data is not None and is_not_found(data):
                        # Т-Банк 30.10.2026 отдал ошибку на «Кредитные карты» и
                        # «Black», которые сутками раньше читались: сбой сайта, а
                        # не удалённая страница. Одна повторная попытка в конце
                        # очереди; настоящая 404 останется 404.
                        if url not in retried:
                            retried.add(url)
                            queue.append(url)
                            visited -= 1
                            log.info("%s: страница ошибки — повторю позже: %s",
                                     self.title, urlsplit(url).path)
                            continue
                        # РостФинанс на неверный адрес отдаёт «Такой страницы нет» с
                        # блоком «Лучшие предложения» — из него получался
                        # продукт «Классический Рост» на каждой странице.
                        failures.append(f"{url}: страница 404")
                        log.warning("%s: страницы нет (404) — %s", self.title,
                                    urlsplit(url).path)
                        continue
                    if data is None:
                        blocked = True
                        failures.append(f"{url}: сайт закрыл доступ (заглушка защиты)")
                        queue.appendleft(url)
                        break

                    family = self._family(url)
                    links = self._links(data.get("links") or [])
                    # Меню и подвал ведут во все разделы — по ним видно,
                    # какие категории розницы у банка есть вообще.
                    coverage.collect(
                        [item[0] if isinstance(item, (list, tuple)) else str(item)
                         for item in data.get("links") or []],
                        site_sections, base_url=self.base_url)
                    self._save_page(visited, url, data, links)
                    office_url = office_url or office_link(data.get("links") or [],
                                                           self.base_url)
                    path = urlsplit(url).path
                    deeper = {l for l in links if urlsplit(l).path.startswith(path + "/")}
                    # Главный продукт — всегда страница продукта, даже если
                    # у него есть подстраницы: у Т-Банка «Кредит наличными»
                    # ссылается на /cash-loan/auto и т. п. и иначе читался
                    # как раздел — продукт не создавался.
                    is_listing = url in seed_set or (url not in first_set
                                                     and len(deeper) >= 3)

                    if is_listing:
                        # С витрины берём пары «название — ставка»: пригодятся
                        # тем продуктам, у которых на своей странице цифры нет.
                        # С главной страницы карточки не берём: раздела у
                        # них нет, а сами продукты есть на витринах разделов
                        # («Карта Ультра» на главной и «Ультра» в картах).
                        items = extract_products(data.get("text") or "") if family else []
                        for item in items:
                            if not is_product_title(item.title):
                                continue
                            showcase.setdefault(normalize_title(item.title),
                                                (item, url, family))
                    else:
                        product = product_from_page(
                            data, bank=self.title, url=url, category=family,
                            region=region_label, collected_at=now)
                        if product is not None:
                            key = normalize_title(product.title)
                            # «Карта ЛУКОЙЛ» у Т-Банка — и дебетовая, и кредитная
                            # (30.10.2026): одно название, разные продукты.
                            if key in products and products[key].category != product.category:
                                key = f"{key} · {product.category.lower()}"
                            products.setdefault(key, product)
                            if (product.rate_min is None
                                    and product.category in _RATE_CATEGORIES):
                                self._rate_from_tariff(product, data, visited)
                            if _worth_saving(product):
                                self._save_missing(url, data, product)
                    # Калькулятор бывает и на витрине (ипотека Сбера — на
                    # /credits/homenew), поэтому — для любой страницы.
                    if data.get("calculator") or data.get("network"):
                        self._save_calculator(url, data, family,
                                              None if is_listing else product, calc_blocked)

                    for link in links:
                        popularity[link] = popularity.get(link, 0) + 1
                        if link not in seen:
                            seen.add(link)
                            queue.append(link)
                # Присутствие в ЛНР: есть ли Луганск на странице офисов банка.
                # Одна страница сверх лимита — и только если сайт не закрылся.
                if office_url and not blocked:
                    site_sections.update(self._presence(reader, office_url, visited + 1))
            self._save_summary(visited, queue, failures)
            # Полнота обхода — в охват: сколько страниц прочитано и какие
            # продуктовые остались непрочитанными (лимит, защита, ошибки).
            unread = [u for u in queue if not _LISTING.search(urlsplit(u).path)]
            site_sections.update({
                CRAWL_READ_KEY: str(visited),
                CRAWL_SITEMAP_KEY: str(len(sitemap_found)),
                CRAWL_UNREAD_KEY: " ".join(unread[:60]),
                CRAWL_FAILED_KEY: " ".join(f.split(":")[0] + ":" + f.split(":")[1]
                                           for f in failures if f.startswith("http"))[:3000],
            })
        except BrowserUnavailable as exc:
            if not products and not showcase:
                return self._failed(str(exc))
            failures.append(f"браузер: {str(exc)[:80]}")
            log.warning("%s: браузер перестал отвечать, собранное сохраняю — %s",
                        self.title, str(exc)[:160])

        merged = self._merge(products, showcase, region_label, now)
        mark_blocked(merged, calc_blocked)
        if blocked:
            log.warning("%s: обход остановлен — сайт закрыл доступ после %s страниц, "
                        "в очереди осталось %s. Собранное сохранено; при следующем "
                        "сборе можно увеличить паузу: banks.%s.pause_s",
                        self.title, visited, len(queue), self.code)
        elif queue:
            log.warning("%s: обход остановлен на пределе в %s страниц, в очереди "
                        "осталось %s. Увеличить: banks.%s.max_pages",
                        self.title, max_pages, len(queue), self.code)
        log.info("%s: обход занял %.0f с, страниц %s, продуктов %s, из них со ставкой %s",
                 self.title, time.monotonic() - started, visited, len(merged),
                 sum(1 for p in merged if p.rate_min is not None))

        if not merged:
            return self._failed("ни одного продукта не найдено: "
                                + ("; ".join(failures[:3]) or "проверьте витрины"))
        return self._result(products=merged, pages_visited=visited, coverage=site_sections,
                            region_applied=applied, region_method=method,
                            partial=blocked or bool(queue))

    @staticmethod
    def _next(queue: deque[str], popularity: dict[str, int]) -> str:
        """Самый упоминаемый адрес из очереди; при равенстве — раньше найденный."""
        best = max(range(len(queue)), key=lambda i: (popularity.get(queue[i], 0), -i))
        url = queue[best]
        del queue[best]
        return url

    def _after_block(self, reader: Any, url: str) -> dict[str, Any] | None:
        """Сайт отдал заглушку защиты: пауза, свежий браузер, одна попытка.

        Защиту не обходим — только сбавляем темп, как сделал бы человек.
        Если и после паузы заглушка, обход останавливается: собранное до
        этого сохраняется, а в итоге видно, на какой странице закрыли доступ.
        """
        wait = float(self.settings.get("block_pause_s", 300))
        attempts = max(1, int(self.settings.get("block_retries", 1)))
        for attempt in range(1, attempts + 1):
            log.warning("%s: сайт отдал заглушку защиты вместо страницы — пауза %.0f с "
                        "и повтор со свежим браузером (%s из %s)",
                        self.title, wait, attempt, attempts)
            reader.close()
            time.sleep(wait)
            data = reader.read(url)
            if not is_blocked(data):
                return data
        log.warning("%s: доступ по-прежнему закрыт — обход остановлен, "
                    "собранное сохраняется", self.title)
        return None

    def _pages_dir(self) -> Path | None:
        """Куда класть тексты всех прочитанных страниц.

        По умолчанию — data/pages-all/<банк> при каждом сборе: по полному
        снимку разбор дорабатывается без новых заходов на сайты (одного
        сбора хватает, чтобы проверить разбор на всех страницах сразу).
        check-bank задаёт свою папку.
        """
        folder = self.settings.get("pages_dir")
        if folder:
            return Path(folder)
        return Path(__file__).resolve().parents[2] / "data" / "pages-all" / self.code

    def _save_page(self, number: int, url: str, data: dict[str, Any],
                   links: list[str]) -> None:
        """Текст прочитанной страницы в файл — для разбора без новых заходов."""
        folder = self._pages_dir()
        if folder is None:
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        name = re.sub(r"[^a-z0-9]+", "-", urlsplit(url).path.lower()).strip("-")[:80]
        own = urlsplit(self.base_url).netloc
        other = sorted({str(item[0] if isinstance(item, (list, tuple)) else item)
                        for item in data.get("links") or []} - set(links))
        other = [l for l in other if urlsplit(l).netloc != own][:200]
        body = [f"URL: {url}", f"H1: {data.get('h1', '')}",
                f"TITLE: {data.get('title', '')}",
                f"РАЗДЕЛ: {self._family(url) or ''}",
                f"ВКЛАДОК НАЖАТО: {data.get('expanded', 0)}",
                f"ССЫЛКИ ДЛЯ ОБХОДА ({len(links)}):", *links, "",
                f"ССЫЛКИ НА ДРУГИЕ САЙТЫ ({len(other)}):", *other, "", "ТЕКСТ:",
                data.get("text") or ""]
        (folder / f"{number:03d}-{name or 'root'}.txt").write_text(
            "\n".join(body), encoding="utf-8")

    def _save_calculator(self, url: str, data: dict[str, Any], family: str,
                         product: Product | None, blocked: dict[str, str]) -> None:
        """Что показал калькулятор: в условия продукта, в отметки недоступности
        и в файлы для доработки (рядом со «Страницами без ставки»)."""
        import json
        from . import calculator
        result = data.get("calculator") or {}
        line = calculator.summary(result) if result.get("options") else ""
        if product is not None and line:
            product.terms["Калькулятор на сайте"] = line
        # Ставку на странице банк не пишет, а калькулятор показывает только
        # платёж (автокредит Сбера) — ставка, выведенная из платежа. В
        # рейтинг она не идёт: это оценка, а не условие банка.
        implied = next((o.get("rate_implied") for o in result.get("options") or []
                        if o.get("rate_implied")), None)
        if product is not None and implied and product.rate_min is None:
            product.terms[IMPLIED_KEY] = f"≈{implied:g} %".replace(".", ",")
        day = datetime.now().strftime("%d.%m.%Y")
        for goal, note in calculator.blocked_goals(result):
            probe = Product(bank=self.title, title=goal, category=family or "Ипотека")
            program = market_program(probe)
            if program:
                blocked.setdefault(program, (
                    f"калькулятор на сайте банка для «{result.get('region') or 'ЛНР'}» "
                    f"на «{goal}» при всех программах пишет «{note}» (сбор {day})"))
        try:
            folder = self._missing_dir()
            folder.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-z0-9]+", "-", urlsplit(url).path.lower()).strip("-")[:80]
            if result:
                (folder / f"calc-{name or 'page'}.json").write_text(
                    json.dumps({"url": url, **result}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
            if data.get("network"):
                (folder / f"net-{name or 'page'}.json").write_text(
                    json.dumps(data["network"], ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("Калькулятор не сохранился: %s", exc)

    def _rate_from_tariff(self, product: Product, data: dict[str, Any], number: int) -> None:
        """Ставки на странице нет — ищем её в PDF-тарифе по ссылке со страницы.

        Текст тарифа сохраняется в снимок страниц: по нему видно, верно ли
        взята цифра. Тарифов за сбор — не больше 25, чтобы не растягивать сбор."""
        from .. import tariffs
        if not self.settings.get("tariff_pdf", True):
            return
        self._tariffs_read = getattr(self, "_tariffs_read", 0)
        # Один тариф висит на многих страницах (рефинансирование Т-Банка —
        # пять страниц, один PDF): скачиваем его один раз за сбор.
        cache: dict[str, str] = self.__dict__.setdefault("_tariff_cache", {})
        for url in tariffs.tariff_links(data.get("links") or []):
            if url in cache:
                text = cache[url]
            else:
                if self._tariffs_read >= 40:
                    return
                self._tariffs_read += 1
                try:
                    text = tariffs.pdf_text(url)
                except Exception as exc:            # noqa: BLE001
                    log.info("%s: тариф %s не прочитался — %s", self.title, url, str(exc)[:100])
                    cache[url] = ""
                    continue
                cache[url] = text
            if not text:
                continue
            folder = self._pages_dir()
            if folder is not None:
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    name = re.sub(r"[^a-z0-9]+", "-", urlsplit(url).path.lower()).strip("-")[-60:]
                    (folder / f"{number:03d}-pdf-{name}.txt").write_text(
                        f"URL: {url}\nПРОДУКТ: {product.title}\n\nТЕКСТ:\n{text}",
                        encoding="utf-8")
                except OSError:
                    pass
            found = tariffs.rate_from_text(text, ceiling=_TARIFF_MAX.get(product.category, 60.0))
            if found:
                low, high, quote = found
                product.rate_min, product.rate_max = low, high
                product.rate_raw = quote
                product.terms[tariffs.SOURCE_KEY] = url
                product.terms[tariffs.QUOTE_KEY] = quote
                product.terms["Источник ставки на странице"] = "тариф банка (PDF)"
                product.terms.pop("Ставка", None)
                return

    def _sitemap_urls(self, reader: Any) -> list[str]:
        """Адреса розницы из карты сайта банка (sitemap.xml и вложенные).

        Только разделы этого банка, без служебных и SEO-страниц. Карты нет
        или не открылась — пусто, обход идёт по ссылкам, как раньше."""
        if not self.settings.get("sitemap"):
            return []
        host = urlsplit(self.base_url).netloc
        todo, found, read = [self.base_url.rstrip("/") + "/sitemap.xml"], [], 0
        while todo and read < 6:
            url = todo.pop(0)
            read += 1
            try:
                data = reader.read(url)
            except Exception as exc:                # noqa: BLE001
                log.info("%s: карта сайта %s не прочиталась — %s", self.title, url,
                         str(exc)[:80])
                continue
            if not data or is_blocked(data):
                continue
            for link in re.findall(r"https?://[^\s<>\"']+", data.get("text") or ""):
                link = link.rstrip(".,;")
                if urlsplit(link).netloc != host:
                    continue
                if link.endswith(".xml"):
                    # Вложенные карты — только про частных клиентов.
                    if re.search(r"person|private|retail|chastn|fiz|main|ru", link, re.I):
                        todo.append(link)
                    continue
                if self._links([link]):
                    found.append(self._normalize(link))
        if found:
            log.info("%s: карта сайта — страниц розницы %s", self.title, len(set(found)))
        return list(dict.fromkeys(found))

    def _presence(self, reader: Any, url: str, number: int) -> dict[str, str]:
        """Страница офисов банка: найден ли там Луганск — с цитатой адреса.

        Ответ кладётся в охват (две служебные строки), он хранится по
        сборам и переносится из прошлого сбора, как ссылки на разделы."""
        log.info("%s: присутствие в ЛНР — страница офисов %s", self.title,
                 urlsplit(url).path)
        try:
            data = reader.read(url)
        except Exception as exc:                    # noqa: BLE001
            log.warning("%s: страница офисов не прочиталась — %s", self.title,
                        str(exc)[:120])
            return {}
        if not data or is_blocked(data):
            return {}
        self._save_page(number, url, data, [])
        text = "\n".join(filter(None, [data.get("text"), data.get("text_after")]))
        quote = lugansk_quote(text)
        return {OFFICES_KEY: url,
                OFFICES_PROOF_KEY: quote or "на странице офисов банка Луганск не найден"}

    def _missing_dir(self) -> Path:
        root = Path(self.settings.get("missing_dir") or "data/pages-missing")
        if not root.is_absolute():
            root = Path(__file__).resolve().parents[2] / root
        return root / self.code

    def _clear_missing(self) -> None:
        """Перед сбором — убрать страницы прошлого сбора: в архивах только свежие."""
        for folder in (self._missing_dir(), self._pages_dir()):
            for item in folder.glob("*.*") if folder and folder.is_dir() else ():
                try:
                    item.unlink()
                except OSError:
                    pass

    def _save_missing(self, url: str, data: dict[str, Any],
                      product: Product | None = None) -> None:
        """Страница продукта, где ставка не нашлась, — в data/pages-missing.

        Пишется при каждом сборе: по этим текстам дорабатывается разбор, и
        не нужно ни ручных скриншотов, ни отдельных проверок страниц, от
        которых сайт банка включает защиту.
        """
        try:
            folder = self._missing_dir()
            folder.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-z0-9]+", "-", urlsplit(url).path.lower()).strip("-")[:80]
            (folder / f"{name or 'page'}.txt").write_text(
                f"URL: {url}\nH1: {data.get('h1', '')}\nРАЗБОР: {_found(product)}\nВКЛАДОК НАЖАТО: "
                f"{data.get('expanded', 0)}\nСОБРАНО: {datetime.now():%d.%m.%Y %H:%M}\n\n"
                + (data.get("text") or ""), encoding="utf-8")
        except OSError as exc:
            log.debug("Страница без ставки не сохранилась: %s", exc)

    def _save_summary(self, visited: int, queue: Any, failures: list[str]) -> None:
        folder = self._pages_dir()
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)
        lines = [f"Прочитано страниц: {visited}",
                 f"Осталось в очереди (упёрлись в max_pages): {len(queue)}", *queue,
                 "", f"Не прочитались ({len(failures)}):", *failures]
        (folder / "000-summary.txt").write_text("\n".join(lines), encoding="utf-8")

    def _merge(self, products: dict[str, Product],
               showcase: dict[str, tuple[Any, str, str]],
               region: str, now: str) -> list[Product]:
        """Страницы продуктов плюс то, что есть только на витринах."""
        for key, (item, url, family) in showcase.items():
            product = products.get(key)
            if product is None:
                # На витрине название короче, чем на странице продукта:
                # «Кредит на образование» и «Кредит на образование с
                # господдержкой» — один продукт, а не два.
                product = next((p for k, p in products.items()
                                if k.startswith(key + " ") and "#" not in p.url_path), None)
                if product is not None and product.rate_min is not None:
                    continue
            if product is None:
                # Своей страницы у продукта нет, витрина общая на несколько
                # продуктов — к адресу добавляем название, иначе у них
                # совпадёт ключ и история изменений склеит их в один.
                product = Product(
                    bank=self.title, url_path=f"{urlsplit(url).path}#{key}",
                    title=item.title,
                    category=category_for(item.title, family), region=region,
                    source_url=url, collected_at=now,
                )
                products[key] = product
            elif product.rate_min is not None:
                continue
            product.rate_min, product.rate_max = item.rate_min, item.rate_max
            product.rate_raw = item.rate_raw
            product.terms.pop("Ставка", None)
            product.terms["Источник ставки"] = f"карточка на витрине {url}"
            conditions.remember(product, conditions.scan(getattr(item, "context", "")))
        return list(products.values())

    def _normalize(self, url: str) -> str:
        parts = urlsplit(url)
        base = urlsplit(self.base_url)
        host = parts.netloc.lower()
        if host in (base.netloc, base.netloc.removeprefix("www.")):
            host = base.netloc
        path = parts.path if self.keep_slash else parts.path.rstrip("/")
        return urlunsplit((base.scheme, host, path or "/", "", ""))

    def _family(self, url: str) -> str:
        path = urlsplit(url).path
        for prefix, category in self.families:
            if path == prefix or path.startswith(prefix + "/"):
                return category
        for pattern, category in self.family_words:
            if re.search(pattern, path, re.I):
                return category
        return ""

    def _links(self, raw: list[Any]) -> list[str]:
        """Ссылки на страницы розницы этого банка, без служебных."""
        base_host = urlsplit(self.base_url).netloc
        out: list[str] = []
        for item in raw:
            href = item[0] if isinstance(item, (list, tuple)) else str(item)
            if not href.startswith("http"):
                continue
            url = self._normalize(href)
            parts = urlsplit(url)
            if parts.netloc != base_host or _FILE.search(parts.path):
                continue
            # Склеенные адреса из меню («…/www.koronapay.com», «…/+74957253141»,
            # «…/ipoteka/[…](https://…)») — не страницы сайта.
            if re.search(r"www\.|\+7|%20|\[|https?:", parts.path):
                continue
            if not self._family(url) or self.skip.search(parts.path) or is_seo_page(url):
                continue
            if url not in out:
                out.append(url)
        return out
