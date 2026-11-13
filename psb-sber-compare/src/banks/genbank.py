"""Генбанк включён по справочнику подразделений Банка России.

ДО «Луганск», Советская, 86А, открыт 14.04.2026.
Доступность каждого продукта требует отдельного подтверждения.
"""

from urllib.parse import urlsplit

from .. import coverage
from .base import registry
from .crawl_adapter import CrawlAdapter


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
