"""Загрузка условий Сбера из файла выгрузки.

Данные по Сберу приходят отдельно, поэтому загрузчик намеренно всеядный:
Excel, CSV или JSON. Названия колонок распознаём по синонимам — выгрузки
редко приходят дважды в одном и том же виде.

Принцип: если колонку опознать не удалось, мы говорим об этом вслух и
оставляем поле пустым. Догадываться и подставлять правдоподобное нельзя —
на этих цифрах человек принимает решения.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..psb.parser import Product, Promo, parse_money, parse_rates, parse_term_months

log = logging.getLogger(__name__)

# Синонимы названий колонок. Сопоставление по нормализованному имени.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "product_key": ("ключ", "код", "id", "идентификатор", "артикул", "code"),
    "title": ("продукт", "название", "наименование", "название продукта", "title", "name"),
    "category": ("категория", "тип", "группа", "сегмент", "category"),
    "rate": ("ставка", "процентная ставка", "ставка %", "ставка, %", "rate", "%"),
    "apr": ("пск", "полная стоимость", "полная стоимость кредита", "apr"),
    "amount": ("сумма", "сумма кредита", "лимит", "сумма вклада", "amount"),
    "term": ("срок", "срок кредита", "срок вклада", "term"),
    "region": ("регион", "территория", "госб", "region"),
    "promo": ("акция", "акции", "спецпредложение", "промо", "promo"),
    "url": ("ссылка", "url", "источник", "link"),
}

_NORM_RE = re.compile(r"[^a-zа-яё0-9%]+", re.I)


def _normalize(name: str) -> str:
    return _NORM_RE.sub(" ", str(name).strip().lower()).strip()


def map_columns(headers: list[str]) -> dict[str, str]:
    """headers → {каноническое поле: исходное имя колонки}."""
    mapping: dict[str, str] = {}
    normalized = {h: _normalize(h) for h in headers}

    for field, aliases in COLUMN_ALIASES.items():
        for header, norm in normalized.items():
            if header in mapping.values():
                continue
            if norm in aliases or any(norm.startswith(a) for a in aliases):
                mapping[field] = header
                break

    missing = [f for f in ("title", "rate") if f not in mapping]
    if missing:
        log.warning(
            "В выгрузке Сбера не распознаны колонки: %s. Доступные заголовки: %s",
            ", ".join(missing), ", ".join(headers),
        )
    return mapping


def _rows_from_file(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    suffix = path.suffix.lower()

    if suffix in {".xlsx", ".xlsm", ".xls"}:
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise RuntimeError(
                "Для чтения Excel нужен openpyxl: pip install openpyxl"
            ) from exc
        book = openpyxl.load_workbook(path, data_only=True)
        sheet = book.active
        raw = list(sheet.iter_rows(values_only=True))
        if not raw:
            return [], []
        headers = [str(h) if h is not None else f"col{i}" for i, h in enumerate(raw[0])]
        rows = [dict(zip(headers, line)) for line in raw[1:] if any(v is not None for v in line)]
        return rows, headers

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("products", [])
        headers = list(rows[0].keys()) if rows else []
        return rows, headers

    if suffix in {".csv", ".tsv", ".txt"}:
        import csv

        delimiter = "\t" if suffix == ".tsv" else None
        text = path.read_text(encoding="utf-8-sig")
        if delimiter is None:
            sample = text[:4096]
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])

    raise ValueError(f"Неизвестный формат выгрузки: {path.suffix}")


def _cell(row: dict[str, Any], mapping: dict[str, str], field: str) -> str:
    header = mapping.get(field)
    if not header:
        return ""
    value = row.get(header)
    return "" if value is None else str(value).strip()


def load_sber(path: str | Path, *, region: str = "", collected_at: str = "") -> tuple[list[Product], list[Promo]]:
    """Читает выгрузку Сбера → список Product и список акций."""
    path = Path(path)
    if not path.exists():
        log.warning("Файл выгрузки Сбера не найден: %s — раздел останется пустым", path)
        return [], []

    rows, headers = _rows_from_file(path)
    if not rows:
        log.warning("Выгрузка Сбера пуста: %s", path)
        return [], []

    mapping = map_columns(headers)
    log.info("Колонки Сбера распознаны: %s",
             ", ".join(f"{k}←{v}" for k, v in mapping.items()) or "ничего")

    products: list[Product] = []
    promos: list[Promo] = []

    for row in rows:
        title = _cell(row, mapping, "title")
        if not title:
            continue

        rate_raw = _cell(row, mapping, "rate")
        apr_raw = _cell(row, mapping, "apr")
        amount_raw = _cell(row, mapping, "amount")
        term_raw = _cell(row, mapping, "term")

        rates = parse_rates(rate_raw) or _bare_numbers(rate_raw)
        aprs = parse_rates(apr_raw) or _bare_numbers(apr_raw)
        amounts = parse_money(amount_raw) or _bare_numbers(amount_raw, minimum=1000)
        terms = parse_term_months(term_raw) or [int(x) for x in _bare_numbers(term_raw)]

        product = Product(
            bank="Сбер",
            url_path=_cell(row, mapping, "url"),
            title=title,
            category=_cell(row, mapping, "category"),
            section="",
            region=_cell(row, mapping, "region") or region,
            rate_min=min(rates) if rates else None,
            rate_max=max(rates) if rates else None,
            rate_raw=rate_raw,
            apr_min=min(aprs) if aprs else None,
            apr_max=max(aprs) if aprs else None,
            apr_raw=apr_raw,
            amount_min=min(amounts) if amounts else None,
            amount_max=max(amounts) if amounts else None,
            amount_raw=amount_raw,
            term_min_months=min(terms) if terms else None,
            term_max_months=max(terms) if terms else None,
            term_raw=term_raw,
            source_url=_cell(row, mapping, "url"),
            collected_at=collected_at,
        )
        # Ключ из выгрузки, иначе — название: оно стабильнее порядка строк.
        object.__setattr__(product, "product_key",
                           _cell(row, mapping, "product_key") or title)

        # Все нераспознанные колонки сохраняем как есть — пригодятся в отчёте.
        known = set(mapping.values())
        for header, value in row.items():
            if header not in known and value not in (None, ""):
                product.terms[str(header)] = str(value)

        products.append(product)

        promo_text = _cell(row, mapping, "promo")
        if promo_text:
            promos.append(Promo(
                title=promo_text[:250],
                text=f"Продукт: {title}",
                source_path=title,
                url=product.source_url,
                content_type="СберВыгрузка",
                segment=product.category,
            ))

    log.info("Из выгрузки Сбера прочитано продуктов: %s, акций: %s", len(products), len(promos))
    return products, promos


def _bare_numbers(text: str, minimum: float = 0.0) -> list[float]:
    """Числа без единиц: в выгрузках ставку часто пишут просто «16,9»."""
    if not text:
        return []
    out = []
    for match in re.finditer(r"\d+(?:[.,]\d+)?", text.replace(" ", "")):
        try:
            value = float(match.group().replace(",", "."))
        except ValueError:
            continue
        if value >= minimum:
            out.append(value)
    return out
