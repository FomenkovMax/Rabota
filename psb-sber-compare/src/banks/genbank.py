"""Генбанк включён по справочнику подразделений Банка России.

ДО «Луганск», Советская, 86А, открыт 14.04.2026.
Доступность каждого продукта требует отдельного подтверждения.
"""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..psb.parser import Product

from .. import coverage
from .base import registry
from .crawl_adapter import CrawlAdapter, is_product_title

ARCHIVE_CARD = "Источник условий: витрина"
_CARD_CLASSES = {"b-product-row", "b-offer", "b-card-business"}
_CATALOGUES = {
    "/chastnym-litsam/deposits/",
    "/chastnym-litsam/credit_for_clients/avtokreditovani/",
    "/chastnym-litsam/credit_for_clients/kredity-dlya-chastnykh-lits/",
    "/chastnym-litsam/mortgage/",
    "/chastnym-litsam/insurance/",
}


class _CatalogueCards(HTMLParser):
    """Extract each tile independently so neighbouring tariffs cannot mix."""

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.cards: list[tuple[str, str, str]] = []
        self.depth = 0
        self.in_heading = False
        self.heading: list[str] = []
        self.lines: list[str] = []
        self.link = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif _CARD_CLASSES.intersection((attrs.get("class") or "").split()):
                self.depth = 1
                self.heading, self.lines, self.link = [], [], ""
        if not self.depth:
            return
        if tag in {"h2", "h3"} and not self.heading:
            self.in_heading = True
        if tag == "a":
            link = urlsplit(urljoin(self.url, attrs.get("href") or ""))
            if (link.scheme == "https" and link.netloc == "www.genbank.ru"
                    and link.path.startswith("/chastnym-litsam/")
                    and link.path != urlsplit(self.url).path):
                if not self.link or "b-button--border" in (attrs.get("class") or "").split():
                    self.link = link._replace(query="", fragment="").geturl()

    def handle_endtag(self, tag):
        if tag in {"h2", "h3"}:
            self.in_heading = False
        if tag != "div" or not self.depth:
            return
        self.depth -= 1
        if not self.depth and self.heading and self.link:
            self.cards.append((self.link, " ".join(self.heading), "\n".join(self.lines)))

    def handle_data(self, data):
        text = " ".join(data.split())
        if self.depth and text:
            self.lines.append(text)
            if self.in_heading:
                self.heading.append(text)


def catalogue_archive_products(folder: Path, *, region: str) -> list[Product]:
    """Replay saved official catalogue tiles with their original date and source."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    products: dict[str, Product] = {}
    for page in manifest:
        source = page["url"]
        parts = urlsplit(source)
        if parts.scheme != "https" or parts.netloc != "www.genbank.ru" or parts.path not in _CATALOGUES:
            continue
        parser = _CatalogueCards(source)
        parser.feed((folder / Path(page["html"]).name).read_text(encoding="utf-8"))
        parser.close()
        for url, title, terms in parser.cards:
            if not is_product_title(title):
                continue
            path = urlsplit(url).path
            category = coverage.classify(url)
            if path.endswith(("/kopilka/", "/nakopitelnyy-schyet-v-rublyakh/")):
                category = "Накопительные счета"
            if category == "Потребительские кредиты":
                category = "Кредиты"
            if not category:
                continue
            # A catalogue offer does not establish the base tariff or city coverage.
            product = Product(bank="Генбанк", title=title, category=category,
                              url_path=path, source_url=url, region=region,
                              collected_at=page["saved_at"], terms={
                                  ARCHIVE_CARD: source,
                                  "Условия на витрине": terms,
                              })
            if url not in products or product.collected_at > products[url].collected_at:
                products[url] = product
    return list(products.values())


@registry.register
class GenbankAdapter(CrawlAdapter):
    code = "genbank"
    title = "Генбанк"
    strategy = "браузер: каталог розничных продуктов"
    verified = False
    base_url = "https://www.genbank.ru"
    seeds = (base_url + "/",)
    families = (("/", "Прочее"),)
    keep_slash = True

    def _family(self, url: str) -> str:
        path = urlsplit(url).path
        if path == "/":
            return "Прочее"
        if path.startswith("/chastnym-litsam/discounts/"):
            return "Лояльность и кешбэк"
        if path.startswith(("/chastnym-litsam/raschetno-kassovoe-obsluzhivanie/",
                            "/chastnym-litsam/yuridicheskie-i-konsaltingovye-uslugi/",
                            "/chastnym-litsam/uslugi/", "/chastnym-litsam/tariff/",
                            "/services/")):
            return "Прочее"
        category = coverage.classify(url)
        return {"Потребительские кредиты": "Кредиты"}.get(category, category or "")
