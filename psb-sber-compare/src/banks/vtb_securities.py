"""Replay VTB's published lists with their precise purpose and source."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html import unescape
from pathlib import Path

from ..psb.parser import Product
from ..securities import DOCUMENT_SCOPE, ISIN, KIND, valid_isin

_BASE = "https://www.vtb.ru/media-files/vtb.ru/sitepages/personal/investicii/marzhinalnoe-kreditovanie/"
PORTFOLIO_NAME = "vtb-portfolio-securities.xlsx"
PLACEMENTS_NAME = "vtb-financed-placements.pdf"
TARIFFS_NAME = "vtb-bond-tariffs.html"
PORTFOLIO_SOURCE = _BASE + (
    "spisok_cennykh_bumag_dokhody_po_kotorym_mogut_byt_vklyucheny_v_sostav_portfeley_klientov_31072026.xlsx"
)
PLACEMENTS_SOURCE = _BASE + "spisok_bumag_po_zayzvkam_na_razmeheniyah__v_marzhu.pdf"
TARIFFS_SOURCE = "https://www.vtb.ru/personal/investicii/tarify/"
_SERVICE_PATH = "/personal/investicii/marzhinalnoe-kreditovanie/"
_BOND_SECTION = re.compile(r"Список субординированных облигаций ВТБ\b.*?</h2>(.*?)<h2\b", re.S)
_BOND_ROW = re.compile(r"(СУБ-Т[12]-\d+)\s+(?:ISIN:\s*)?(RU(?:\s*[A-Z0-9]){9,10})\b")
_SUB_T1_8_ISSUE = "https://www.moex.com/ru/listing/securities-cards.aspx?code=RU000A103S89"
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


def tariff_bonds(path: Path) -> list[Product]:
    if not path.is_file():
        return []
    try:
        page = path.read_text(encoding="utf-8")
        section = _BOND_SECTION.search(page)
        if not section:
            raise ValueError("Раздел субординированных облигаций отсутствует")
        body = unescape(re.sub(r"<[^>]+>", " ", section[1]))
        products = []
        for title, code in _BOND_ROW.findall(body):
            code = "".join(code.split())
            readback = ""
            if (title, code) == ("СУБ-Т1-8", "RU000A103S8"):
                code = "RU000A103S89"
                readback = _SUB_T1_8_ISSUE
            if not valid_isin(code):
                raise ValueError(f"Некорректный ISIN в строке {title}")
            product = _product(
                code, title, TARIFFS_SOURCE, "Перечень субординированных облигаций в тарифах ВТБ",
                "Облигация",
            )
            if readback:
                product.terms["Источник проверки ISIN"] = readback
                product.terms["Квалификация инвестора"] = "Для квалифицированных инвесторов"
            products.append(product)
        if not products or len({p.terms[ISIN] for p in products}) != len(products):
            raise ValueError("Не удалось выделить уникальные выпуски")
        return products
    except (OSError, ValueError) as error:
        log.warning("Не прочитан перечень облигаций ВТБ %s: %s", path, error)
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
    portfolio = portfolio_products(directory / PORTFOLIO_NAME, identities)
    for product in portfolio:
        identities.setdefault(product.terms[ISIN], product)
    return (portfolio + placement_products(directory / PLACEMENTS_NAME, identities)
            + tariff_bonds(directory / TARIFFS_NAME))
