"""Очистка источников: HTML и PDF → текст, нормализация, проверка цитат, обрезка."""

from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_NUMERIC_LINE = re.compile(r"\d")


def normalize(text: str) -> str:
    """Неразрывные и любые пробельные символы → один пробел."""
    return _WS.sub(" ", text.replace(" ", " ").replace(" ", " ")).strip()


def evidence_in_source(evidence: str, source: str) -> bool:
    quote = normalize(evidence or "")
    return bool(quote) and quote.casefold() in normalize(source).casefold()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [normalize(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        table.replace_with("\n" + "\n".join(rows) + "\n")
    lines = (normalize(line) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def pdf_to_text(data: bytes) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                parts.extend("| " + " | ".join(c or "" for c in row) + " |" for row in table)
            parts.append(page.extract_text() or "")
    return "\n".join(p for p in parts if p.strip())


def trim_relevant(text: str, max_chars: int = 12_000) -> str:
    """Длинный текст сокращается до строк с цифрами и их соседей — там живут условия."""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if _NUMERIC_LINE.search(line):
            keep.update({i - 1, i, i + 1})
    out, size = [], 0
    for i in sorted(k for k in keep if 0 <= k < len(lines)):
        if size + len(lines[i]) + 1 > max_chars:
            break
        out.append(lines[i])
        size += len(lines[i]) + 1
    return "\n".join(out)
