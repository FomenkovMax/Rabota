"""Identify security issues without confusing yields with bank interest rates."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

KIND = "Вид ценной бумаги"
ISIN = "ISIN"
_CODE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")


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


def remember(product, body: list[str]) -> None:
    if product.category != "Инвестиции":
        return
    path = urlsplit(product.source_url).path
    title = product.title
    kind = ("Облигация" if re.search(r"/bonds/[^/]+|\bоблигаци", path + " " + title, re.I)
            else "Акция" if re.search(r"/stocks/[^/]+|\bакци[яиюй]\b", path + " " + title, re.I)
            else "")
    # An index/listing is not a specific issue. A unique ISIN can identify
    # an issue even when the heading omits the instrument type.
    codes = sorted({c for c in _CODE.findall("\n".join([title, *body])) if valid_isin(c)})
    if not kind and len(codes) != 1:
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


def groups(products):
    """Group only by verified-format ISIN; missing identifiers never merge."""
    out = {}
    for product in products:
        terms = product.terms or {}
        if not terms.get(KIND):
            continue
        code = terms.get(ISIN, "")
        key = code if valid_isin(code) else (product.bank, product.source_url, product.title)
        out.setdefault(key, []).append(product)
    return list(out.values())
