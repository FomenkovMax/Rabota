"""Identify security issues without confusing yields with bank interest rates."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from .psb.parser import Product

log = logging.getLogger(__name__)

CATALOGUE_SOURCE = "Источник ценной бумаги: витрина"
KIND = "Вид ценной бумаги"
ISIN = "ISIN"
_CODE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")


def issue_kind(url: str) -> str:
    path = urlsplit(url).path
    match = re.search(r"/(stocks|bonds)/([^/]+)/?$", path, re.I)
    if not match or match[2].lower() in {"offer", "offer_ofz", "all", "catalog"}:
        return ""
    return "Акция" if match[1].lower() == "stocks" else "Облигация"


def valid_isin(value: str) -> bool:
    """Check the identifier's shape and check digit, not its current listing."""
    if not _CODE.fullmatch(value):
        return False
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    total = 0
    for i, digit in enumerate(reversed(digits)):
        n = int(digit) * (2 if i % 2 else 1)
        total += n // 10 + n % 10
    return total % 10 == 0


def remember(product, body: list[str], *, page_title: str = "") -> None:
    if product.category != "Инвестиции":
        return
    path = urlsplit(product.source_url).path
    title = product.title
    if re.search(r"/(?:edu|digest|events|memos|news|blog|journal)(?:/|$)", path, re.I):
        return
    issue_path = re.search(r"/(?:stocks|bonds)/([^/]+)/?$", path, re.I)
    if issue_path and issue_path.group(1).lower() in {"offer", "offer_ofz", "all", "catalog"}:
        return
    kind = issue_kind(product.source_url) or (
            "Облигация" if re.search(r"\bоблигаци", title, re.I)
            else "Акция" if re.search(r"\bакци[яиюй]\b", title, re.I)
            else "")
    # An index/listing is not a specific issue. A unique ISIN can identify
    # an issue even when the heading omits the instrument type.
    codes = sorted({c for c in _CODE.findall("\n".join([title, *body])) if valid_isin(c)})
    # T-Bank labels the instrument in the document title. For OFZs the URL
    # slug can differ from the ISIN printed there for the issue.
    if issue_path and urlsplit(product.source_url).hostname == "www.tbank.ru":
        match = re.search(r"^Купить облигации .+? \(([A-Z]{2}[A-Z0-9]{9}[0-9])\)", page_title, re.I)
        if match and valid_isin(match[1]):
            codes = [match[1]]
    if not issue_path and len(codes) != 1:
        return
    product.terms[KIND] = kind or "Ценная бумага"
    if len(codes) == 1:
        product.terms[ISIN] = codes[0]
    elif codes:
        product.terms["ISIN требует проверки"] = ", ".join(codes)
    product.terms["Доступность торгов в Луганске"] = (
        "Наличие страницы не подтверждает возможность покупки через банк в Луганске; "
        "требуется проверка брокерского обслуживания и ограничений этого выпуска")
    # Preserve labelled source values verbatim. A coupon is not a deposit
    # rate; a market price is not guaranteed and requires a quote timestamp.
    labels = {
        "Тикер": r"тикер|ticker",
        "Валюта бумаги": r"валюта(?: номинала| торгов)?",
        "Номинал": r"номинал(?:ьная стоимость)?",
        "Дата погашения": r"дата погашения|погашение",
        "Купон": r"купон(?:ная ставка)?",
        "Квалификация инвестора": r"для квалифицированных инвесторов",
    }
    for key, pattern in labels.items():
        for index, line in enumerate(body):
            if re.match(r"^(?:" + pattern + r")(?:\s*[:—–-]\s*|$)", line, re.I):
                quote = line
                if re.fullmatch(pattern + r"\s*:?", line, re.I) and index + 1 < len(body):
                    quote += ": " + body[index + 1]
                product.terms[key] = quote[:300]
                break


def catalogue_products(directory: Path, existing) -> list[Product]:
    """Use labelled listing data only where the detail page is absent."""
    seen = {p.source_url.rstrip("/") for p in existing if p.source_url}
    products = []
    for kind in ("stocks", "bonds"):
        path = directory / (kind + ".json")
        if not path.is_file():
            continue
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("Не прочитан каталог бумаг %s: %s", path, error)
            continue
        root = f"https://www.tbank.ru/invest/{kind}/"
        if not isinstance(source, dict) or source.get("source") != root:
            continue
        for page, snapshot in source.get("pages", {}).items():
            page_url = urlsplit(page)
            if not page.startswith(root) or page_url.path != urlsplit(root).path:
                continue
            for url, row in snapshot.get("rows", {}).items():
                canonical = url.rstrip("/")
                if canonical in seen or not url.startswith(root) or not issue_kind(url):
                    continue
                symbol = row.get("symbol", {})
                title = symbol.get("showName")
                if not title:
                    continue
                terms = {KIND: issue_kind(url), CATALOGUE_SOURCE: page}
                code = str(symbol.get("isin") or "")
                if valid_isin(code):
                    terms[ISIN] = code
                fields = {"Тикер": symbol.get("ticker"), "Валюта бумаги": symbol.get("currency"),
                          "Размер лота": symbol.get("lotSize")}
                details = row.get("fields", {})
                fields.update({"Номинал": details.get("faceValue"), "Купон": details.get("couponValue"),
                               "Дата погашения": details.get("matDate")})
                terms.update({label: str(value) for label, value in fields.items() if value not in (None, "")})
                products.append(Product(
                    bank="Т-Банк", title=title, category="Инвестиции", source_url=url,
                    url_path=urlsplit(url).path, terms=terms,
                    collected_at=snapshot.get("read_at") or source.get("updated_at", ""),
                ))
                seen.add(canonical)
    return products


def groups(products):
    """Group only by verified-format ISIN; missing identifiers never merge."""
    out = {}
    for product in products:
        terms = product.terms or {}
        if not terms.get(KIND):
            continue
        code = str(terms.get(ISIN) or "")
        path = urlsplit(product.source_url).path
        if re.search(r"/(?:edu|digest|events|memos|news|blog|journal)(?:/|$)", path, re.I):
            continue
        issue_path = re.search(r"/(?:stocks|bonds)/([^/]+)/?$", path, re.I)
        if not valid_isin(code) and not issue_path:
            continue
        if issue_path and issue_path.group(1).lower() in {"offer", "offer_ofz", "all", "catalog"}:
            continue
        key = code if valid_isin(code) else (product.bank, product.source_url, product.title)
        out.setdefault(key, []).append(product)
    return list(out.values())
