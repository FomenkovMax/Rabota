"""Охват: какие категории розницы есть у банка и какие собраны агентом.

Аудит 07.10.2026 просил матрицу «банк × категория» по всему Розничному
блоку: вклады, карты, кредиты, ипотека, но и инвестиции, страхование,
НПФ, переводы, лояльность, ячейки, валюта. Ставки по последним
сравнивать не договорились — достаточно факта «есть у банка» со ссылкой.

Факт берётся из ссылок самого сайта банка: меню и подвал любой страницы
ведут во все разделы розницы. Ссылка на раздел — проверяемое
доказательство: по ней можно перейти и убедиться.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlsplit

#: Категории ТЗ — в порядке показа в матрице.
CATEGORIES = (
    "Вклады",
    "Накопительные счета",
    "Дебетовые карты",
    "Кредитные карты",
    "Потребительские кредиты",
    "Автокредиты",
    "Ипотека",
    "Инвестиции",
    "Страхование",
    "НПФ и ПДС",
    "Переводы и платежи",
    "Лояльность и кешбэк",
    "Сейфовые ячейки",
    "Валютные операции",
)

# Категорию задаёт раздел сайта — первый значимый сегмент адреса, а
# уточняют её только родственные подразделы: «/vklady-i-scheta/invest-plus»
# — вклад, а не инвестиции; «/deposits/vklady-dolgosrochnye» — вклад, а
# не ПДС; «/bank_cards/credit» — кредитная карта.
_PREFIX = {"ru", "en", "person", "personal", "individual", "individuals",
           "chastnym-licam", "fiz", "private", "retail"}
_SECTION: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Страхование", re.compile(r"^(?:strahov\w*|insurance|polis\w*)$", re.I)),
    ("Инвестиции", re.compile(r"^(?:invest\w*|broker\w*|iis|wealth|brokerage)$", re.I)),
    ("НПФ и ПДС", re.compile(r"^(?:pds|npf|pension[-_]?savings|pensionnye[-\w]*)$", re.I)),
    ("Сейфовые ячейки", re.compile(r"^(?:seif\w*|sejf\w*|seyf\w*|safe[-_\w]*|yachejk\w*)$", re.I)),
    ("Валютные операции", re.compile(r"^(?:valyut\w*|currency\w*|exchange\w*|obmen\w*|fx)$", re.I)),
    ("Переводы и платежи", re.compile(
        r"^(?:perevod\w*|transfers?|payments?|platezh\w*|sbp|ecommerce|pay)$", re.I)),
    ("Лояльность и кешбэк", re.compile(
        r"^(?:cashback\w*|kesh\w*|bonus\w*|loyalty\w*|spasibo|privileg\w*|"
        r"subscriptions?|podpisk\w*|pro|prime\w*)$", re.I)),
    ("Ипотека", re.compile(r"^(?:mortgage\w*|ipotek\w*)$", re.I)),
    ("cards", re.compile(
        r"^(?:cards?|karty|bank_cards|debetcards|debit[-_]?cards|creditcards|"
        r"credit[-_]?cards|pensioncards)$", re.I)),
    ("loans", re.compile(r"^(?:loans?|kredit\w*|credits?|zaim\w*|zaym\w*|avtokredit\w*)$", re.I)),
    ("savings", re.compile(
        r"^(?:deposits?|vklad\w*|vklady[-\w]*|saving|savings|savingsaccount|contributions)$",
        re.I)),
)
_SAFE = re.compile(r"seif|sejf|seyf|yachejk|yacheyk", re.I)
_CREDIT = re.compile(r"credit|kredit", re.I)
_HOME = re.compile(r"^(?:home\w*|homenew|ipotek\w*|mortgage\w*)$", re.I)
_AUTO = re.compile(r"auto|avto|carloan", re.I)
_SAVINGS_ACCOUNT = re.compile(r"nakopit|saving[-_]?account|savingsaccount|^nakopi$|-schet$", re.I)
_FILE = re.compile(r"\.(?:pdf|docx?|xlsx?|zip|jpe?g|png|svg)$", re.I)
_SERVICE_HOST = re.compile(r"^(?:cdn|static|online|ib|lk|api|promokod|my|app)\.", re.I)

# Не розница для физлиц и не разделы: бизнес, о банке, новости, помощь.
_NOT_RETAIL = re.compile(
    r"business|/biz\b|/corp|corporate|/legal|/msb\b|/sme\b|s_m_business|/about|"
    r"/news|/press|career|vacanc|/help|/faq|/blog|/journal|/login|/auth|"
    r"/offices?\b|/atm\b|/contacts?\b", re.I)


def classify(url: str) -> str | None:
    """Категория ТЗ по адресу страницы. None — не раздел розницы."""
    parts = urlsplit(url or "")
    path = parts.path
    if (not path or path == "/" or _NOT_RETAIL.search(path) or _FILE.search(path)
            or _SERVICE_HOST.match(parts.netloc.lower().removeprefix("www."))):
        return None
    segments = [s for s in path.strip("/").split("/") if s]
    while segments and segments[0].lower() in _PREFIX:
        segments = segments[1:]
    if not segments:
        return None
    rest = segments[1:]
    if any(_SAFE.search(s) for s in segments):
        return "Сейфовые ячейки"
    # «/person/person-deposit», «/person/obmen-valjuty»,
    # «/person/payments-and-transfers» (ЦМР): раздел — первое слово сегмента.
    top = re.sub(r"^(?:person|personal)[-_]", "", segments[0], flags=re.I)
    candidates = (top, re.split(r"[-_]", top)[0])
    for category, pattern in _SECTION:
        if not any(pattern.match(c) for c in candidates):
            continue
        if category == "cards":
            return "Кредитные карты" if (_CREDIT.search(top) or any(
                _CREDIT.search(s) for s in rest)) else "Дебетовые карты"
        if category == "loans":
            # «Кредит под залог авто» — кредит наличными, не автокредит.
            if (_AUTO.search(top) or any(_AUTO.search(s) for s in rest)) and not any(
                    "zalog" in s.lower() for s in segments):
                return "Автокредиты"
            if any(_HOME.match(s) for s in rest):
                return "Ипотека"
            if any(re.search(r"card|kart", s, re.I) for s in rest):
                return "Кредитные карты"
            return "Потребительские кредиты"
        if category == "savings":
            return ("Накопительные счета" if any(_SAVINGS_ACCOUNT.search(s) for s in rest)
                    or _SAVINGS_ACCOUNT.search(top) else "Вклады")
        return category
    return None


def same_site(url: str, base_url: str) -> bool:
    """Ссылка ведёт на сайт банка (поддомены — тоже его сайт)."""
    host = urlsplit(url or "").netloc.lower().removeprefix("www.")
    base = urlsplit(base_url or "").netloc.lower().removeprefix("www.")
    return bool(host and base) and (host == base or host.endswith("." + base))


def collect(urls: Iterable[str], found: dict[str, str], *, base_url: str = "") -> None:
    """Дополняет `found` (категория → первая ссылка) ссылками со страницы."""
    for url in urls:
        if base_url and not same_site(url, base_url):
            continue
        category = classify(url)
        if not category:
            continue
        clean = url.split("#")[0].split("?")[0]
        # Ссылка на корень раздела нагляднее ссылки на акцию внутри него.
        if category not in found or len(clean) < len(found[category]):
            found[category] = clean


# --- матрица ---------------------------------------------------------------

COMPARED, COLLECTED, LINK_ONLY, NOT_FOUND = "compared", "collected", "link", "none"
STATUS_LABEL = {
    COMPARED: "сравнивается",
    COLLECTED: "собрано, без сравнения ставок",
    LINK_ONLY: "есть у банка (ссылка), не собирается",
    NOT_FOUND: "не найдено на сайте",
}

# Категория продукта в агенте → категория ТЗ.
_PRODUCT_TO_TZ = {
    "Вклады": "Вклады",
    "Накопительные счета": "Накопительные счета",
    "Дебетовые карты": "Дебетовые карты",
    "Банковские карты": "Дебетовые карты",
    "Зарплатные карты": "Дебетовые карты",
    "Пенсионные карты": "Дебетовые карты",
    "Кредитные карты": "Кредитные карты",
    "Кредиты": "Потребительские кредиты",
    "Ипотека": "Ипотека",
    "Страхование": "Страхование",
    "Долгосрочные сбережения": "НПФ и ПДС",
    "Пенсионные продукты": "НПФ и ПДС",
    "Счета и переводы": "Переводы и платежи",
    "Акции и спецпредложения": "Лояльность и кешбэк",
}
_RATED_TZ = {"Вклады", "Накопительные счета", "Кредитные карты",
             "Потребительские кредиты", "Автокредиты", "Ипотека"}


def tz_category(product: Any) -> str | None:
    """Категория ТЗ для продукта агента."""
    category = getattr(product, "category", "") or ""
    tz = _PRODUCT_TO_TZ.get(category)
    if tz == "Потребительские кредиты":
        title = (getattr(product, "title", "") or "").lower()
        if re.search(r"автокредит|на\s+авто|на\s+автомобил", title) and "залог" not in title:
            return "Автокредиты"
    return tz


@dataclass
class Cell:
    status: str
    products: int = 0
    rated: int = 0
    url: str = ""

    @property
    def label(self) -> str:
        return STATUS_LABEL[self.status]


def matrix(banks: list[str], products: Iterable[Any],
           links: dict[str, dict[str, str]]) -> dict[str, dict[str, Cell]]:
    """category → bank → Cell."""
    counts: dict[tuple[str, str], list[int]] = {}
    first_url: dict[tuple[str, str], str] = {}
    for product in products:
        tz = tz_category(product)
        if tz is None:
            continue
        key = (tz, product.bank)
        slot = counts.setdefault(key, [0, 0])
        slot[0] += 1
        has_rate = product.rate_min is not None or product.rate_max is not None
        if has_rate and tz in _RATED_TZ:
            slot[1] += 1
        first_url.setdefault(key, getattr(product, "source_url", "") or "")

    out: dict[str, dict[str, Cell]] = {}
    for tz in CATEGORIES:
        row: dict[str, Cell] = {}
        for bank in banks:
            total, rated = counts.get((tz, bank), [0, 0])
            link = (links.get(bank) or {}).get(tz, "")
            if rated:
                cell = Cell(COMPARED, total, rated, first_url.get((tz, bank), link))
            elif total:
                cell = Cell(COLLECTED, total, 0, first_url.get((tz, bank), link))
            elif link:
                cell = Cell(LINK_ONLY, 0, 0, link)
            else:
                cell = Cell(NOT_FOUND)
            row[bank] = cell
        out[tz] = row
    return out
