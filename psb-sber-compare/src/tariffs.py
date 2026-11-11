"""Ставка из тарифа банка (PDF), когда на странице продукта её нет.

У части продуктов ставка опубликована только в документе: кредит наличными
Т-Банка (сбор 28.10.2026) — «Процентная ставка рассчитывается индивидуально
в пределах указанного в тарифе диапазона», а сам тариф — PDF по ссылке
«Тарифы». Здесь такой PDF скачивается, его текст сохраняется в снимок
страниц (для проверки), а ставка берётся, только если в тексте она прямо
подписана как процентная ставка.

Ставка из тарифа — официальный документ банка, но разметка у PDF разная:
в отчёте она помечена «из тарифа (PDF)» и идёт со средней достоверностью.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SOURCE_KEY = "Тариф (PDF)"
QUOTE_KEY = "Ставка из тарифа (PDF)"

# Ссылка на тариф: по подписи или по имени файла. Требования к залогу,
# списки документов, правила программ лояльности — не тарифы.
_TARIFF = re.compile(r"тариф|tarif|tariff|процентн\w+\s+ставк", re.I)
_NOT_TARIFF = re.compile(r"requirement|documents?-required|loyalty|program|terms-of-|promo|"
                         r"требовани|перечень\s+документ|правила\s+программ|анкет", re.I)

_RATE = re.compile(
    r"(?:процентн\w+\s+)?ставк\w*[^\n%]{0,80}?(?:от\s+|до\s+)?(\d{1,2}(?:[,.]\d{1,3})?)\s?%"
    r"(?:\s*(?:[-–—]|до)\s*(\d{1,2}(?:[,.]\d{1,3})?)\s?%)?", re.I)
_NOT_RATE = re.compile(r"неустойк|штраф|пен[яи]\b|ключев\w*\s+ставк|полн\w+\s+стоимост|\bпск\b|"
                       r"льготн\w+\s+период|беспроцентн", re.I)


def tariff_links(links: list[Any], *, limit: int = 2) -> list[str]:
    """PDF-тарифы среди ссылок страницы (пары «адрес, подпись»)."""
    out: list[str] = []
    for item in links:
        if isinstance(item, (list, tuple)):
            href = str(item[0]) if item else ""
            text = str(item[1]) if len(item) > 1 else ""
        else:
            href, text = str(item), ""
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        if _NOT_TARIFF.search(href) or _NOT_TARIFF.search(text):
            continue
        if _TARIFF.search(text) or _TARIFF.search(href):
            out.append(href)
        if len(out) >= limit:
            break
    return list(dict.fromkeys(out))


def pdf_text(url: str, *, timeout: int = 30, max_bytes: int = 6_000_000,
             max_pages: int = 12) -> str:
    """Текст PDF по ссылке — с российскими корнями сертификатов, как у ПСБ."""
    import requests

    from .psb.client import build_ca_bundle
    response = requests.get(url, timeout=timeout, verify=build_ca_bundle(),
                            headers={"User-Agent": "Mozilla/5.0"}, stream=True)
    response.raise_for_status()
    data = response.raw.read(max_bytes + 1, decode_content=True)
    if len(data) > max_bytes:
        raise ValueError(f"PDF больше {max_bytes // 1_000_000} МБ")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages[:max_pages]]
    return "\n".join(pages)


# Тарифы Т-Банка (сбор 29.10.2026): заголовок «1. Процентная ставка»
# отдельной строкой, цифры — ниже: «от 16,9% до 22% годовых».
_HEADING = re.compile(r"^\s*\d+\.?\s*процентн\w+\s+ставк\w*\s*:?\s*$", re.I | re.M)
# Следующий раздел верхнего уровня: «2. Плата…», но не подпункт «1.1. базовая».
_NEXT_SECTION = re.compile(r"^\s*\d+\.\s+\S", re.M)
# Первое число диапазона бывает без «%»: «от 0,01 до 31,0% годовых» (автокредит).
_FROM_TO = re.compile(r"^\s*(?:от\s+)?(\d{1,2}(?:[,.]\d{1,3})?)\s?%?\s*"
                      r"(?:(?:до|[-–—])\s*(\d{1,2}(?:[,.]\d{1,3})?)\s?%)?\s*(?:годовых)?\s*$",
                      re.I | re.M)


def _rate_under_heading(text: str, ceiling: float) -> tuple[float, float, str] | None:
    for heading in _HEADING.finditer(text):
        tail = text[heading.end():heading.end() + 1200]
        stop = _NEXT_SECTION.search(tail)
        block = tail[:stop.start()] if stop else tail
        for match in _FROM_TO.finditer(block):
            if "%" not in match.group(0):
                continue
            low = float(match.group(1).replace(",", "."))
            high = float((match.group(2) or match.group(1)).replace(",", "."))
            if 0 < low <= high <= ceiling:
                quote = f"{heading.group(0).strip().rstrip(':')}: {' '.join(match.group(0).split())}"
                return low, high, quote[:200]
    return None


def rate_from_text(text: str, *, ceiling: float = 60.0) -> tuple[float, float, str] | None:
    """(от, до, цитата) — ставка, прямо подписанная как процентная ставка:
    в одной строке с подписью или под заголовком «N. Процентная ставка»."""
    under = _rate_under_heading(text or "", ceiling)
    if under:
        return under
    for match in _RATE.finditer(text or ""):
        quote = " ".join(match.group(0).split())
        line_start = text.rfind("\n", 0, match.start()) + 1
        context = text[line_start:match.end()]
        if _NOT_RATE.search(context):
            continue
        low = float(match.group(1).replace(",", "."))
        high = float((match.group(2) or match.group(1)).replace(",", "."))
        if not 0 < low <= high <= ceiling:
            continue
        return low, high, quote[:200]
    return None
