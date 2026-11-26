"""Official PSB list for margin trades, with the scope stated for each issue."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from ..securities import DOCUMENT_SCOPE, ISIN, KIND, valid_isin
from .parser import Product

SOURCE = ("https://www.psbank.ru/qpstorage/psb/images/personal/wealth/"
          "margin_lending/general_list_CBR_margin_landing.pdf")
FILE_NAME = "psb-liquid-securities.pdf"
SCOPE = "Перечень ПСБ для необеспеченных сделок"
_TITLE = re.compile(r"Список ценных бумаг для совершения необеспеченных сделок на (\d{2}\.\d{2}\.\d{4})")
_ROW = re.compile(r"(?m)^(\d+)[ \t]*([A-Z][A-Z0-9.-]*)[ \t]+(.*?)(?=^\d+[ \t]*[A-Z]|\Z)", re.S)
_INSTRUMENT = re.compile(
    r"\s+(?:акция|(?:биржев\w*|государствен\w*|корпоратив\w*|субфедеральн\w*|"
    r"муниципальн\w*)\s+облигаци\w*|еврооблигаци\w*|облигаци\w*)", re.I,
)
_POSITIONS = re.compile(r"(long(?:\s*/\s*short)?|short)\s", re.I)
log = logging.getLogger(__name__)


def parse(text: str) -> list[Product]:
    date_match = _TITLE.search(text)
    if not date_match:
        raise ValueError("Не найден заголовок перечня ПСБ с датой")
    published = datetime.strptime(date_match[1], "%d.%m.%Y").date().isoformat()
    products = []
    sections = re.split(r"(?m)^[ \t]*(Акции|Облигации|Фонды|Валюта)[ \t]*$", text.replace("\f", "\n"))
    if sections[1:6:2] != ["Акции", "Облигации", "Фонды"]:
        raise ValueError("Изменились заголовки разделов перечня ПСБ")
    content = dict(zip(sections[1::2], sections[2::2]))
    for section, kind in (("Акции", "Акция"), ("Облигации", "Облигация")):
        rows = list(_ROW.finditer(content.get(section, "")))
        if not rows:
            raise ValueError(f"В перечне ПСБ нет строк раздела «{section}»")
        tickers = set()
        for number, row in enumerate(rows, 1):
            index, ticker, fields = row.groups()
            name, *instrument = _INSTRUMENT.split(fields, maxsplit=1)
            positions = _POSITIONS.search(instrument[0]) if instrument else None
            title = " ".join(name.split())
            if int(index) != number or not positions or not title or ticker in tickers:
                raise ValueError(f"Строка {number} раздела «{section}» требует проверки")
            tickers.add(ticker)
            terms = {
                KIND: kind,
                "Тикер": ticker,
                DOCUMENT_SCOPE: SCOPE,
                "Дата перечня": published,
                "Маржинальная позиция": "".join(positions[1].split()).lower(),
            }
            if valid_isin(ticker):
                terms[ISIN] = ticker
            products.append(Product(
                bank="ПСБ", title=title, category="Инвестиции",
                source_url=SOURCE, url_path="/personal/wealth/markets/",
                terms=terms, collected_at=published,
            ))
    return products


def load(path: Path) -> list[Product]:
    if not path.is_file():
        return []
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        with path.open("rb") as document:
            return parse("\n".join(page.extract_text() or "" for page in PdfReader(document).pages))
    except (OSError, PdfReadError, ValueError) as error:
        log.warning("Не прочитан перечень ПСБ %s: %s", path, error)
        return []


def refresh(path: Path) -> int:
    """Download and validate the updated document before replacing the local copy."""
    import requests

    from .client import build_ca_bundle

    limit = 6_000_000
    with requests.get(SOURCE, timeout=20, verify=build_ca_bundle(), stream=True) as response:
        response.raise_for_status()
        raw = response.raw.read(limit + 1, decode_content=True)
    if len(raw) > limit or not raw.startswith(b"%PDF"):
        raise ValueError("ПСБ не вернул PDF ожидаемого размера")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".pdf", delete=False) as temp:
        temp.write(raw)
        candidate = Path(temp.name)
    try:
        products = load(candidate)
        if not products:
            raise ValueError("Полученный перечень ПСБ не прошёл проверку строк")
        candidate.replace(path)
        return len(products)
    finally:
        candidate.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Обновить официальный перечень ПСБ для необеспеченных сделок")
    cli.add_argument("output", nargs="?", default=Path("data") / FILE_NAME, type=Path)
    output = cli.parse_args().output
    print(f"Сверено выпусков: {refresh(output)}. Документ: {output}")
