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
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..psb.parser import Product, parse_money, parse_term_months
from .base import BankAdapter, CollectResult
from .browser import (BrowserSettings, BrowserUnavailable, PageFailed,
                      PageReader, PageTooSlow)
from .generic_site import category_for, extract_products, rates_of

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

# Заголовок страницы-раздела, а не продукта.
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
_PSK = re.compile(r"\bпск\b|полная стоимость", re.I)
_FILE = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar)$", re.I)
_QUOTES = re.compile(r"[«»\"'„“”+]")


def normalize_title(title: str) -> str:
    """Ключ для сопоставления названий с витрины и со страницы продукта."""
    text = _QUOTES.sub(" ", title.replace("ё", "е").replace("Ё", "Е"))
    return " ".join(text.lower().split())


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
    if start < 0:
        return title, []

    body: list[str] = []
    for line in lines[start + len(head): start + len(head) + 40]:
        if _STOP_LINE.match(line):
            break
        body.append(line)
    return title, body


def product_from_page(data: dict[str, Any], *, bank: str, url: str,
                      category: str, region: str, collected_at: str) -> Product | None:
    """Продукт со страницы продукта. None — если это не страница продукта."""
    title, body = describe_page(data)
    if not title or _GENERIC_TITLE.match(title):
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
        # ПСК — полная стоимость кредита, а не ставка. Кладём её в своё
        # поле: в светофоре ставка сравнивается со ставкой, не с ПСК.
        if _PSK.search(line) or _PSK.search(following):
            product.apr_min, product.apr_max = min(values), max(values)
            product.apr_raw = f"{line} {following}".strip()
            continue
        product.rate_min, product.rate_max = min(values), max(values)
        product.rate_raw = line
        break

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
    #: Разделы розницы: (префикс пути, категория по умолчанию). Порядок
    #: важен — более точный префикс идёт раньше общего.
    families: tuple[tuple[str, str], ...] = ()
    #: Служебные страницы внутри разделов: справка, калькуляторы, архивы.
    skip: re.Pattern[str] = re.compile(r"$^")
    protection: str = ""
    wait_for: str = ""
    sets_region: bool = False

    def collect(self) -> CollectResult:
        if not self.seeds or not self.families:
            return self._failed("не заданы витрины и разделы для обхода")

        settings = BrowserSettings.from_config(self.settings.get("browser"))
        now = datetime.now().isoformat(timespec="seconds")
        region_cookies = self.settings.get("region_cookies") or []
        applied = self.sets_region or bool(region_cookies)
        if applied:
            region_label = self.settings.get("region_label", "")
        else:
            region_label = "регион на сайте не выбран"
            log.warning("%s: регион на сайте не задаётся — условия будут те, что "
                        "сайт отдаёт по умолчанию. Настроить: banks.%s.region_cookies",
                        self.title, self.code)

        max_pages = int(self.settings.get("max_pages") or 80)
        limit_s = float(self.settings.get("section_timeout_s") or 0)

        seeds = [self._normalize(url) for url in self.seeds]
        seed_set = set(seeds)
        queue: deque[str] = deque(seeds)
        seen: set[str] = set(seeds)

        products: dict[str, Product] = {}
        showcase: dict[str, tuple[Any, str, str]] = {}
        failures: list[str] = []
        visited = 0
        started = time.monotonic()

        try:
            with PageReader(settings, cookies=region_cookies or None,
                            wait_for=self.wait_for, limit_s=limit_s) as reader:
                while queue and visited < max_pages:
                    url = queue.popleft()
                    visited += 1
                    log.info("%s: страница %s (в очереди %s) — %s",
                             self.title, visited, len(queue), urlsplit(url).path)
                    try:
                        data = reader.read(url)
                    except (PageTooSlow, PageFailed) as exc:
                        failures.append(f"{url}: {str(exc)[:80]}")
                        log.warning("%s: страница не прочиталась — %s",
                                    self.title, str(exc)[:160])
                        continue

                    family = self._family(url)
                    links = self._links(data.get("links") or [])
                    path = urlsplit(url).path
                    deeper = {l for l in links if urlsplit(l).path.startswith(path + "/")}
                    is_listing = url in seed_set or len(deeper) >= 3

                    if is_listing:
                        # С витрины берём пары «название — ставка»: пригодятся
                        # тем продуктам, у которых на своей странице цифры нет.
                        for item in extract_products(data.get("text") or ""):
                            showcase.setdefault(normalize_title(item.title),
                                                (item, url, family))
                    else:
                        product = product_from_page(
                            data, bank=self.title, url=url, category=family,
                            region=region_label, collected_at=now)
                        if product is not None:
                            products.setdefault(normalize_title(product.title), product)

                    for link in links:
                        if link not in seen:
                            seen.add(link)
                            queue.append(link)
        except BrowserUnavailable as exc:
            if not products and not showcase:
                return self._failed(str(exc))
            failures.append(f"браузер: {str(exc)[:80]}")
            log.warning("%s: браузер перестал отвечать, собранное сохраняю — %s",
                        self.title, str(exc)[:160])

        merged = self._merge(products, showcase, region_label, now)
        if queue:
            log.warning("%s: обход остановлен на пределе в %s страниц, в очереди "
                        "осталось %s. Увеличить: banks.%s.max_pages",
                        self.title, max_pages, len(queue), self.code)
        log.info("%s: обход занял %.0f с, страниц %s, продуктов %s, из них со ставкой %s",
                 self.title, time.monotonic() - started, visited, len(merged),
                 sum(1 for p in merged if p.rate_min is not None))

        if not merged:
            return self._failed("ни одного продукта не найдено: "
                                + ("; ".join(failures[:3]) or "проверьте витрины"))
        return self._result(products=merged, pages_visited=visited,
                            region_applied=applied)

    def _merge(self, products: dict[str, Product],
               showcase: dict[str, tuple[Any, str, str]],
               region: str, now: str) -> list[Product]:
        """Страницы продуктов плюс то, что есть только на витринах."""
        for key, (item, url, family) in showcase.items():
            product = products.get(key)
            if product is None:
                product = Product(
                    bank=self.title, url_path=urlsplit(url).path, title=item.title,
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
        return list(products.values())

    def _normalize(self, url: str) -> str:
        parts = urlsplit(url)
        base = urlsplit(self.base_url)
        host = parts.netloc.lower()
        if host in (base.netloc, base.netloc.removeprefix("www.")):
            host = base.netloc
        return urlunsplit((base.scheme, host, parts.path.rstrip("/") or "/", "", ""))

    def _family(self, url: str) -> str:
        path = urlsplit(url).path
        for prefix, category in self.families:
            if path == prefix or path.startswith(prefix + "/"):
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
            if not self._family(url) or self.skip.search(parts.path):
                continue
            if url not in out:
                out.append(url)
        return out
