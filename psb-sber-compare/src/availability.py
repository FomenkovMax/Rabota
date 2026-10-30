"""Есть ли продукт в Луганске — главный вопрос ТЗ.

У каждого продукта — один из четырёх статусов и основание для него:

* «есть в ЛНР, условия ЛНР» — регион ЛНР выбран на сайте или в калькуляторе
  банка, либо банк работает только в ЛНР (ЦМР);
* «есть в ЛНР, условия общероссийские» — банк в ЛНР работает (источник в
  настройке presence_source), а отдельных условий для ЛНР на сайте нет:
  по ТЗ тогда берутся общероссийские;
* «нет в ЛНР» — есть прямое указание: калькулятор пишет «недоступно в
  вашем регионе», на странице сказано «не предоставляется в … ЛНР» и т. п.;
* «не установлено» — ни того, ни другого; что проверено, сказано в
  основании. Такие продукты — первые кандидаты на доработку сбора.

Статус не додумывается: каждое основание — это ссылка, цитата или
настройка с источником.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from . import market

LNR, FEDERAL, ABSENT, UNKNOWN = "lnr", "federal", "absent", "unknown"

LABELS = {
    LNR: "есть в ЛНР, условия ЛНР",
    FEDERAL: "есть в ЛНР, условия общероссийские",
    ABSENT: "нет в ЛНР",
    UNKNOWN: "не установлено",
}
ICONS = {LNR: "🟢", FEDERAL: "🔵", ABSENT: "🔴", UNKNOWN: "⚪"}
#: Какой статус сильнее, когда у банка несколько продуктов одной программы.
RANK = {LNR: 3, FEDERAL: 2, UNKNOWN: 1, ABSENT: 0}

_REGION_WORDS = (r"(?:ДНР|ЛНР|Луганск\w*|Донецк\w*|Запорожск\w*|Херсонск\w*|"
                 r"нов\w+\s+(?:регион|субъект|территори)\w*)")
# «Не предоставляется в ДНР, ЛНР…», «недоступна для жителей новых регионов»,
# «кроме Луганской Народной Республики». Только в одном предложении с
# названием региона — общее «не выдаётся» без региона ничего не доказывает.
_CLAUSE = re.compile(
    r"[^.!?\n]{0,120}?(?:\bне\s+(?:предоставля|выда[её]т|выдаю|оформля|обслужива|"
    r"распространя|действу)\w*|недоступ\w*|\bкроме\b|\bза\s+исключением\b)"
    r"[^.!?\n]{0,100}?" + _REGION_WORDS + r"[^.!?\n]{0,60}", re.I)
# Наоборот — программа именно для новых регионов: это не оговорка.
_FOR_REGION = re.compile(r"\bдля\s+(?:жителей\s+)?" + _REGION_WORDS, re.I)


def find_clause(text: str) -> str:
    """Цитата со страницы: продукт в ЛНР/новых регионах не предоставляется."""
    for match in _CLAUSE.finditer(text or ""):
        quote = " ".join(match.group(0).split())
        if _FOR_REGION.search(quote) and not re.search(r"\bне\b|недоступ", quote, re.I):
            continue
        return quote[:220]
    return ""


@dataclass
class Status:
    code: str
    reason: str          # основание: что именно показало
    source: str = ""     # ссылка или настройка

    @property
    def label(self) -> str:
        return LABELS[self.code]

    @property
    def icon(self) -> str:
        return ICONS[self.code]


def status_of(product: Any, *, region_method: str, presence: str = "") -> Status:
    """Статус наличия продукта в ЛНР и основание.

    region_method — как условия банка привязаны к ЛНР (market.method_of):
    selector — регион выбран на сайте, local — банк работает только в ЛНР,
    federal — про ЛНР на сайте ничего нет, not_confirmed — не выбран.
    presence — источник, что банк в ЛНР работает (banks.<код>.presence_source).
    """
    terms = getattr(product, "terms", None) or {}
    url = getattr(product, "source_url", "") or ""
    absent = terms.get(market.REGION_KEY)
    if absent:
        return Status(ABSENT, str(absent), url)
    calc = str(terms.get("Калькулятор на сайте") or "")
    # «Есть в ЛНР» — только если калькулятор для ЛНР показал хоть одну ставку:
    # строка из одних «недоступно» и «не показал расчёт» этого не доказывает.
    if (calc and "регион не выбран" not in calc and re.search(r"луганск", calc, re.I)
            and re.search(r"\d\s?%", calc)):
        return Status(LNR, f"калькулятор на сайте банка: {calc}", url)
    if region_method == "selector":
        return Status(LNR, "условия получены на сайте банка с выбранным регионом ЛНР", url)
    if region_method == "local":
        return Status(LNR, "банк работает только в ЛНР — условия на сайте луганские",
                      presence or url)
    if region_method == "federal":
        if presence:
            return Status(FEDERAL, "банк работает в ЛНР, отдельных условий для ЛНР на "
                                   "сайте нет — по ТЗ берутся общероссийские", presence)
        return Status(UNKNOWN, "отдельных условий для ЛНР на сайте нет, а присутствие "
                               "банка в ЛНР не подтверждено источником", url)
    return Status(UNKNOWN, "регион на сайте банка при сборе не выбран — чьи это "
                           "условия, неизвестно", url)


def statuses(products: Iterable[Any], *, region_methods: dict[str, str],
             presence: dict[str, str]) -> dict[int, Status]:
    """Статус каждого продукта — по id объекта (продукты не хешируются)."""
    return {id(p): status_of(p, region_method=market.method_of(p, region_methods),
                             presence=presence.get(p.bank, ""))
            for p in products}


# --- таблица ТЗ: продукт Сбера × банк --------------------------------------

@dataclass
class Cell:
    status: Status | None          # None — аналога у банка не нашлось
    product: Any = None
    rate: float | None = None


@dataclass
class Row:
    product: Any                   # продукт Сбера
    program: str
    own: Status
    cells: dict[str, Cell]


def _rate(product: Any) -> float | None:
    if product.category in market.SAVINGS:
        return product.rate_max if product.rate_max is not None else product.rate_min
    return product.rate_min if product.rate_min is not None else product.rate_max


def matrix(products: list[Any], *, home: str, banks: list[str],
           status: dict[int, Status]) -> list[Row]:
    """Каждый продукт Сбера и аналоги у каждого банка: та же категория и
    программа (семейная ипотека — с семейной). Из нескольких аналогов банка
    берётся тот, что доступнее в ЛНР, при равенстве — с лучшей ставкой.
    Нишевые и особые продукты Сбера тоже в таблице: по ТЗ — все продукты."""
    by_key: dict[tuple[str, str, str], list[Any]] = {}
    for p in products:
        by_key.setdefault((p.bank, p.category or "", market.program_of(p)), []).append(p)
    rows = []
    for own in sorted((p for p in products if p.bank == home),
                      key=lambda p: (p.category or "", market.program_of(p), p.title)):
        program = market.program_of(own)
        cells: dict[str, Cell] = {}
        for bank in banks:
            if bank == home:
                continue
            twins = by_key.get((bank, own.category or "", program), [])
            if not twins:
                cells[bank] = Cell(None)
                continue
            higher = own.category in market.SAVINGS

            def key(p: Any) -> tuple:
                r = _rate(p)
                return (RANK[status[id(p)].code], r is not None,
                        (r if higher else -r) if r is not None else 0)
            best = max(twins, key=key)
            cells[bank] = Cell(status[id(best)], best, _rate(best))
        rows.append(Row(own, program, status[id(own)], cells))
    return rows


def completeness(products: list[Any], status: dict[int, Status], *, home: str) -> dict[str, int]:
    """Сколько продуктов Сбера в каждом статусе — проверка полноты по ТЗ."""
    out = {code: 0 for code in LABELS}
    for p in products:
        if p.bank == home:
            out[status[id(p)].code] += 1
    return out
