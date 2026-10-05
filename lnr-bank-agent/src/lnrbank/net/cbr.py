"""Ключевая ставка ЦБ из таблицы cbr.ru/hd_base/KeyRate/."""

from __future__ import annotations

import re
from datetime import date, timedelta

import httpx

URL = "https://www.cbr.ru/hd_base/KeyRate/"
_ROW = re.compile(r"<tr>\s*<td>(\d{2})\.(\d{2})\.(\d{4})</td>\s*<td>([\d,]+)</td>\s*</tr>")


def parse_key_rate(html: str) -> tuple[str, float]:
    """Самая свежая строка таблицы: (дата ISO, ставка)."""
    rows = [(f"{y}-{m}-{d}", float(v.replace(",", "."))) for d, m, y, v in _ROW.findall(html)]
    if not rows:
        raise ValueError("В ответе ЦБ нет таблицы ключевой ставки")
    return max(rows)


def fetch_key_rate(verify, on: date | None = None) -> tuple[str, float]:
    on = on or date.today()
    params = {
        "UniDbQuery.Posted": "True",
        "UniDbQuery.From": (on - timedelta(days=30)).strftime("%d.%m.%Y"),
        "UniDbQuery.To": on.strftime("%d.%m.%Y"),
    }
    resp = httpx.get(URL, params=params, verify=verify, timeout=30)
    resp.raise_for_status()
    return parse_key_rate(resp.text)
