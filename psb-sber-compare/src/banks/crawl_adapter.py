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
from .. import conditions, coverage

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
_FILE = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar)$", re.I)
_QUOTES = re.compile(r"[«»\"'„“”+]")


def normalize_title(title: str) -> str:
    """Ключ для сопоставления названий с витрины и со страницы продукта."""
    text = _QUOTES.sub(" ", title.replace("ё", "е").replace("Ё", "Е"))
    return " ".join(text.lower().split())


_IMPERATIVE = re.compile(r"^(?:оформите|откройте)\s+(.+)$", re.I)
_TITLE_TAIL = re.compile(r"\s+(?:со\s+ставкой|с\s+кэшбэком|получайте|онлайн\b|до\s+\d).*$", re.I)


_RATE_IN_TITLE = re.compile(
    r"\s+(?:(?:доходност\w*|ставк\w*)\s+)?(?:до|от|со\s+ставкой)\s+\d[\d,.]*\s?%.*$", re.I)


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


def _rate_conditions(body: list[str], index: int, best: float) -> list[str]:
    """Условия ставки: рядом со строкой ставки и там, где та же цифра повторена.

    «До 14,2%» стоит в шапке, а «14,2% годовых — первые 2 месяца» — ниже,
    в описании (ВТБ-Счёт). Строка с той же цифрой и её соседи и есть
    расшифровка условий.
    """
    found = conditions.near_rate(body, index)
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

    for index, line in enumerate(body):
        values = rates_of(line)
        if values is None:
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
            if product.apr_min is not None:
                values += [product.apr_min, product.apr_max]
            product.apr_min, product.apr_max = min(values), max(values)
            product.apr_raw = f"{line} {following}".strip()
            continue
        product.rate_min, product.rate_max = min(values), max(values)
        product.rate_raw = line
        conditions.remember(product, _rate_conditions(body, index, max(values)))
        break

    # Ставки в описании нет, но она есть в самом заголовке страницы
    # продукта: «ВТБ-Вклад в рублях до 13,7% годовых».
    if product.rate_min is None and headline != title:
        values = rates_of(headline)
        if values:
            conditions.remember(product, conditions.scan(headline)
                                + _rate_conditions(body, 0, max(values)))
            product.rate_min, product.rate_max = min(values), max(values)
            product.rate_raw = headline

    for key, value in _amount_and_term(body).items():
        setattr(product, key, value)

    if product.rate_min is None:
        product.terms["Ставка"] = ("на странице указана только ПСК"
                                   if product.apr_min is not None
                                   else "на странице продукта не указана")
    if body:
        product.terms["Контекст на странице"] = " · ".join(body[:8])[:300]
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
                            products.setdefault(normalize_title(product.title), product)

                    for link in links:
                        popularity[link] = popularity.get(link, 0) + 1
                        if link not in seen:
                            seen.add(link)
                            queue.append(link)
            self._save_summary(visited, queue, failures)
        except BrowserUnavailable as exc:
            if not products and not showcase:
                return self._failed(str(exc))
            failures.append(f"браузер: {str(exc)[:80]}")
            log.warning("%s: браузер перестал отвечать, собранное сохраняю — %s",
                        self.title, str(exc)[:160])

        merged = self._merge(products, showcase, region_label, now)
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
        folder = self.settings.get("pages_dir")
        return Path(folder) if folder else None

    def _save_page(self, number: int, url: str, data: dict[str, Any],
                   links: list[str]) -> None:
        """Текст прочитанной страницы в файл — для разбора, почему чего-то нет.

        Включается только проверкой банка (check-bank): при обычном сборе
        pages_dir не задан и на диск ничего не пишется.
        """
        folder = self._pages_dir()
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-z0-9]+", "-", urlsplit(url).path.lower()).strip("-")[:80]
        own = urlsplit(self.base_url).netloc
        other = sorted({str(item[0] if isinstance(item, (list, tuple)) else item)
                        for item in data.get("links") or []} - set(links))
        other = [l for l in other if urlsplit(l).netloc != own][:200]
        body = [f"URL: {url}", f"H1: {data.get('h1', '')}",
                f"TITLE: {data.get('title', '')}",
                f"ССЫЛКИ ДЛЯ ОБХОДА ({len(links)}):", *links, "",
                f"ССЫЛКИ НА ДРУГИЕ САЙТЫ ({len(other)}):", *other, "", "ТЕКСТ:",
                data.get("text") or ""]
        (folder / f"{number:03d}-{name or 'root'}.txt").write_text(
            "\n".join(body), encoding="utf-8")

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
            if not self._family(url) or self.skip.search(parts.path) or is_seo_page(url):
                continue
            if url not in out:
                out.append(url)
        return out
