"""Разбор по снимку страниц — без заходов на сайты.

Каждый сбор кладёт тексты всех прочитанных страниц в data/pages-all/<банк>
(кнопка бота «Полный снимок страниц»). Здесь эти тексты прогоняются через
тот же разбор, что и при сборе: правку разбора можно проверить на всех
страницах сразу, а не новым сбором.

    python run.py replay путь/к/pages-all
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from . import availability, conditions, market
from .banks import crawl_adapter as crawl

_HEADER = ("URL", "H1", "TITLE", "РАЗДЕЛ", "ВКЛАДОК НАЖАТО")
_BANK = {"sber": "Сбер", "vtb": "ВТБ", "tbank": "Т-Банк", "rostfinance": "РостФинанс",
         "psb": "ПСБ", "cmr": "ЦМР"}


def read_page(path: Path) -> dict[str, Any]:
    """Файл снимка → данные страницы, как их отдаёт браузер."""
    raw = path.read_text(encoding="utf-8")
    head, _, text = raw.partition("\nТЕКСТ:\n")
    data: dict[str, Any] = {"text": text, "links": []}
    for line in head.splitlines():
        key, _, value = line.partition(": ")
        if key in _HEADER:
            data[key] = value.strip()
    return data


def products(folder: Path) -> Iterator[tuple[str, dict[str, Any], Any]]:
    """(банк, данные страницы, продукт или None) по всем страницам снимка."""
    for bank_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        bank = _BANK.get(bank_dir.name, bank_dir.name)
        for path in sorted(bank_dir.glob("*.txt")):
            data = read_page(path)
            if not data.get("URL"):
                continue
            page = {"h1": data.get("H1", ""), "title": data.get("TITLE", ""),
                    "text": data["text"], "links": []}
            product = crawl.product_from_page(
                page, bank=bank, url=data["URL"], category=data.get("РАЗДЕЛ", ""),
                region="ЛНР", collected_at="")
            yield bank, data, product


def report(folder: Path, *, key_rate: float = 14.0) -> list[str]:
    """Строки сводки: банк, раздел, продукт, ставка, ПСК, тип, замечания."""
    lines = []
    for bank, data, p in products(folder):
        if p is None:
            continue
        check = market.assess(p, key_rate=key_rate, region_method="selector")
        kind, _ = conditions.kind_of(p)
        absent = (p.terms or {}).get(market.REGION_KEY, "")
        rate = "—" if p.rate_min is None else (
            f"{p.rate_min:g}" if p.rate_min == p.rate_max else f"{p.rate_min:g}–{p.rate_max:g}")
        apr = "" if p.apr_min is None else f" ПСК {p.apr_min:g}"
        notes = "; ".join(check.issues)
        lines.append(f"{bank}\t{p.category}\t{p.title}\t{rate}{apr}\t"
                     f"{conditions.LABELS[kind]}\t{'НЕТ В ЛНР: ' + absent if absent else ''}\t{notes}")
    return lines
