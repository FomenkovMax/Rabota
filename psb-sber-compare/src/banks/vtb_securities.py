"""Replay VTB's published lists with their precise purpose and source."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from ..psb.parser import Product
from ..securities import DOCUMENT_SCOPE, ISIN, KIND, valid_isin

_BASE = "https://www.vtb.ru/media-files/vtb.ru/sitepages/personal/investicii/marzhinalnoe-kreditovanie/"
PORTFOLIO_NAME = "vtb-portfolio-securities.xlsx"
PLACEMENTS_NAME = "vtb-financed-placements.pdf"
PORTFOLIO_SOURCE = _BASE + (
    "spisok_cennykh_bumag_dokhody_po_kotorym_mogut_byt_vklyucheny_v_sostav_portfeley_klientov_31072026.xlsx"
)
PLACEMENTS_SOURCE = _BASE + "spisok_bumag_po_zayzvkam_na_razmeheniyah__v_marzhu.pdf"
_SERVICE_PATH = "/personal/investicii/marzhinalnoe-kreditovanie/"
log = logging.getLogger(__name__)


def _product(code: str, title: str, source: str, scope: str, kind: str,
             *, date: str = "", ticker: str = "") -> Product:
    terms = {KIND: kind, ISIN: code, DOCUMENT_SCOPE: scope}
    if ticker:
        terms["Тикер"] = ticker
    return Product(bank="ВТБ", title=title, category="Инвестиции", source_url=source,
                   url_path=_SERVICE_PATH, terms=terms, collected_at=date)


def portfolio_products(path: Path, identities: dict[str, Product]) -> list[Product]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException
    from zipfile import BadZipFile

    if not path.is_file():
        return []
    products = []
    try:
        with path.open("rb") as file:
            workbook = load_workbook(file, read_only=True, data_only=True)
            try:
                sheet = workbook.active
                date = datetime.strptime(sheet.title, "%d.%m.%Y").date().isoformat()
                rows = sheet.iter_rows(min_row=2, max_col=3, values_only=True)
                if next(rows, ()) != ("Наименование", "Торговый код", "ISIN"):
                    raise ValueError("Изменились заголовки списка ВТБ")
                for title, ticker, code in rows:
                    if isinstance(code, str) and valid_isin(code) and title and ticker:
                        identified = identities.get(code)
                        kind = identified.terms[KIND] if identified else "Ценная бумага"
                        products.append(_product(
                            code, str(title), PORTFOLIO_SOURCE,
                            "Учёт доходов в портфеле ВТБ", kind, date=date, ticker=str(ticker),
                        ))
            finally:
                workbook.close()
    except (OSError, BadZipFile, InvalidFileException, ValueError) as error:
        log.warning("Не прочитан перечень ВТБ %s: %s", path, error)
        return []
    return products


def placement_products(path: Path, identities: dict[str, Product]) -> list[Product]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not path.is_file():
        return []
    try:
        with path.open("rb") as file:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(file).pages)
        if not re.match(r"\s*ISIN\s", text):
            raise ValueError("Изменился заголовок списка ВТБ")
        products = []
        for code in dict.fromkeys(text.split()[1:]):
            if not valid_isin(code):
                raise ValueError("В списке ВТБ есть строка без корректного ISIN")
            identified = identities.get(code)
            products.append(_product(
                code, identified.title if identified else code, PLACEMENTS_SOURCE,
                "Список ВТБ для заявок на размещение на заёмные средства",
                identified.terms[KIND] if identified else "Ценная бумага",
            ))
        return products
    except (OSError, PdfReadError, ValueError) as error:
        log.warning("Не прочитан перечень ВТБ %s: %s", path, error)
        return []


def load(directory: Path, securities) -> list[Product]:
    kinds: dict[str, set[str]] = {}
    identities = {}
    for product in securities:
        code = product.terms.get(ISIN, "")
        kind = product.terms.get(KIND)
        if kind in {"Акция", "Облигация"} and valid_isin(code):
            identities.setdefault(code, product)
            kinds.setdefault(code, set()).add(kind)
    identities = {code: product for code, product in identities.items() if len(kinds[code]) == 1}
    return (portfolio_products(directory / PORTFOLIO_NAME, identities)
            + placement_products(directory / PLACEMENTS_NAME, identities))
