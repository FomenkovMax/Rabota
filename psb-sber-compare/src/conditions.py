"""Тип ставки: базовая или «особая» — приветственная, премиальная, нишевая.

Аудит 07.10.2026 нашёл главную ошибку сравнения: лучшая ставка банка
бралась вместе с надбавками. «Накопительный ВТБ-Счёт 14,2 %» — это
приветственная ставка на два месяца (базовая 6 %), «ЦМР Старт 15 %» —
вклад до 31 дня, «Накопительный счёт Премиум» Сбера — только для
премиальных клиентов. Сравнивать их с обычными продуктами нельзя.

Тип определяется по названию продукта и по тексту рядом со ставкой —
не по всей странице: «премиальный» и «для новых клиентов» встречаются
в меню и рекламе любой страницы банка.

В «Место Сбера» идут только базовые ставки. Остальные показываются
отдельным блоком «Специальные условия», со ставкой и причиной.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

BASE = "base"
WELCOME = "welcome"
NEW_MONEY = "new_money"
PREMIUM = "premium"
SALARY = "salary"
SUBSCRIPTION = "subscription"
SHORT_TERM = "short_term"
NICHE = "niche"

LABELS = {
    BASE: "базовая",
    WELCOME: "приветственная / для новых клиентов",
    NEW_MONEY: "на «новые деньги»",
    PREMIUM: "для премиальных клиентов",
    SALARY: "для зарплатных клиентов",
    SUBSCRIPTION: "с подпиской или платной услугой",
    SHORT_TERM: "короткий срок",
    NICHE: "нишевый продукт",
}

#: Ключ в `terms`, куда сборщик кладёт найденные рядом со ставкой условия.
TERMS_KEY = "Условия ставки"

# Условия рядом со ставкой. Порядок — по силе: приветственная ставка
# ограничена сроком и кругом клиентов сильнее, чем надбавка за подписку.
_NEAR_RATE: tuple[tuple[str, re.Pattern[str]], ...] = (
    # «Первые N дней» — только рядом со ставкой: у Т-Банка «первые 30 дней»
    # относятся к пополнению вклада, а не к ставке.
    (WELCOME, re.compile(
        r"(?:ставк|%)[^.]{0,40}первы[ехй]\s+\d+\s+(?:дн|мес|календ)\w*|"
        r"первы[ехй]\s+\d+\s+(?:дн|мес|календ)\w*[^.]{0,30}(?:ставк|%)|"
        r"приветственн\w*|для\s+«?нов\w+»?\s+(?:клиент|вкладчик)\w*|"
        r"«?нов\w+»?\s+вкладчик\w*|впервые\s+откры\w*|«?новых»?\s+клиентов", re.I)),
    (NEW_MONEY, re.compile(r"«?нов\w+»?\s+(?:деньг|денег)\w*|«новые»", re.I)),
    (PREMIUM, re.compile(r"премиальн\w*|привилеги\w*|\bprivate\b|премьер", re.I)),
    (SALARY, re.compile(
        r"зарплатн\w+\s+(?:клиент|карт)\w*|получа\w+\s+зарплат\w*|"
        r"с\s+зарплатной\s+картой", re.I)),
    (SUBSCRIPTION, re.compile(
        r"подписк\w*|с\s+услугой\s+«[^»]+»|\d[\d\s]*₽\s+в\s+месяц", re.I)),
    (SHORT_TERM, re.compile(r"до\s+31\s+дн\w*|на\s+1\s+месяц\b", re.I)),
)

# Нишевые продукты — по названию: для узкого круга или с особой механикой.
_NICHE_TITLE = re.compile(
    r"пдс|долгосрочн\w*\s+сбереж|забота\s+о\s+будущем|ставка\s+на\s+будущее|"
    r"драгоцен|металл|социальн|пенсион|\bсво\b|ветеран|участник|"
    r"kids|детск|акционер|инвестиц|двойная\s+выгода|в\s+юан|валют|"
    r"для\s+получателей|почте\s+россии",
    re.I,
)
_PREMIUM_TITLE = re.compile(r"премиум|премьер|\bprime\b|прайм|private|привилеги", re.I)


def scan(text: str) -> list[str]:
    """Условия ставки, найденные в тексте: «приветственная: первые 2 месяца»."""
    found: list[str] = []
    for kind, pattern in _NEAR_RATE:
        match = pattern.search(text or "")
        if match:
            found.append(f"{LABELS[kind]}: «{match.group(0)}»")
    return found


def near_rate(lines: list[str], index: int, *, before: int = 4, after: int = 8) -> list[str]:
    """Условия в окне вокруг строки со ставкой."""
    window = " ".join(lines[max(0, index - before):index + after + 1])
    return scan(window)


def remember(product: Any, found: Iterable[str]) -> None:
    """Кладёт найденные условия в `terms` продукта."""
    found = [item for item in found if item]
    if found:
        terms = getattr(product, "terms", None)
        if terms is not None:
            terms[TERMS_KEY] = "; ".join(dict.fromkeys(found))


def kind_of(product: Any) -> tuple[str, str]:
    """(тип ставки, причина). Базовая — («base», «»)."""
    title = getattr(product, "title", "") or ""
    niche = _NICHE_TITLE.search(title)
    if niche:
        return NICHE, f"нишевый продукт: «{niche.group(0)}» в названии"
    premium = _PREMIUM_TITLE.search(title)
    if premium:
        return PREMIUM, f"для премиальных клиентов: «{premium.group(0)}» в названии"

    terms = getattr(product, "terms", None) or {}
    # «Ставка с зарплатной картой» — отдельная строка, общая ставка
    # продукта уже без неё (ЦМР), поэтому здесь её не учитываем.
    noted = str(terms.get(TERMS_KEY, ""))
    noted += " " + (getattr(product, "rate_conditions", "") or "")
    for kind, label in LABELS.items():
        if kind == BASE:
            continue
        if label in noted:
            reason = next((part.strip() for part in noted.split(";") if label in part), label)
            return kind, reason
    return BASE, ""


def is_comparable(product: Any) -> bool:
    """Ставка базовая — её можно ставить в один ряд с базовыми других банков."""
    return kind_of(product)[0] == BASE
