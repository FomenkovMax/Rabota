"""Адаптер ПСБ (psbank.ru).

Страницы вкладов, накопительных счетов и «спецпредложений» собраны из одинаковых
карточек `.product-card` (проверено на документах от 24.10.2026). Адаптер извлекает
значения ДОСЛОВНО (как напечатано на сайте) и добавляет производные числа, которые
можно получить однозначно. Если на сайте вёрстка изменилась и карточек нет — это
сигнал об ошибке разбора, а не «нет продуктов» (см. ParseError).
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from bankintel.domain.enums import AvailabilityStatus, ProductCategory
from bankintel.sources.base import (
    BankAdapter,
    ConditionRow,
    ExtractedProduct,
    FetchedDocument,
    SourceRef,
    register_adapter,
)
from bankintel.sources.common import (
    ParseError,
    canonical_name,
    clean_text as _clean,
    detect_currency as _currency,
    parse_rate_range,
    rate_json as _rate_json,
)

__all__ = ["PsbAdapter", "ParseError", "canonical_name", "parse_rate_range"]


def _category_by_href(href: str, default: ProductCategory) -> ProductCategory:
    if "/personal/savingsaccount" in href:
        return ProductCategory.SAVINGS
    if "/personal/saving/" in href:
        return ProductCategory.DEPOSIT
    return default


@register_adapter("psb")
class PsbAdapter(BankAdapter):
    PAGE_DEFAULTS = {
        "deposits": ProductCategory.DEPOSIT,
        "savings_accounts": ProductCategory.SAVINGS,
        "savings_offers": ProductCategory.SAVINGS,
    }

    def parse(self, source: SourceRef, doc: FetchedDocument) -> list[ExtractedProduct]:
        default = self.PAGE_DEFAULTS.get(source.key)
        if default is None:
            return []  # неизвестный источник (например site_root) — не разбираем
        soup = BeautifulSoup(doc.content, "html.parser")
        cards = soup.select(".product-card")
        if not cards:
            raise ParseError(f"{source.key}: на странице нет карточек .product-card (вёрстка изменилась?)")
        products, seen = [], set()
        for card in cards:
            product = self._parse_card(card, source, doc, default)
            if product and (product.category, product.name) not in seen:
                seen.add((product.category, product.name))
                products.append(product)
        return products

    def parse_detail(self, source: SourceRef, doc: FetchedDocument) -> list[ConditionRow]:
        """Страница продукта: таблица(ы) `.tariff-block__table`, строки «подпись | значение»."""
        soup = BeautifulSoup(doc.content, "html.parser")
        rows = []
        for tr in soup.select(".tariff-block__table tr"):
            cells = tr.find_all("td")
            if len(cells) != 2:
                continue
            label = _clean(cells[0])
            paragraphs = [_clean(p) for p in cells[1].find_all("p")] or [_clean(cells[1])]
            value = "\n".join(p for p in paragraphs if p)
            if label and value:
                rows.append(ConditionRow(label, value))
        if not rows:
            raise ParseError(f"{source.key}: на странице продукта нет таблицы условий .tariff-block__table")
        return rows

    def _parse_card(self, card: Tag, source: SourceRef, doc: FetchedDocument, default: ProductCategory):
        title_el = card.select_one(".product-card__title")
        title = _clean(title_el)
        if not title:
            return None
        href = title_el.get("href") or ""
        if href and not href.startswith(("/", "http")):
            href = "/" + href  # на сайте встречаются корневые ссылки без ведущего «/»
        category = _category_by_href(href, default)
        advantages = [
            {
                "value": _clean(a.select_one(".product-card__advantage-title")),
                "label": _clean(a.select_one(".product-card__advantage-text")) or "",
            }
            for a in card.select(".product-card__advantage")
        ]
        params: dict = {
            "kind": "card",
            "page_key": source.key,
            "title": title,
            "product_url": urljoin(doc.url, href) if href else None,
            "description": _clean(card.select_one(".product-card__description")),
            "advantages": advantages,
        }
        evidence: dict[str, str] = {"title": title}
        for adv in advantages:
            label, value = adv["label"].lower(), adv["value"] or ""
            if label.startswith("сумма"):
                params["amount_text"], params["currency"] = value, _currency(value)
                evidence["amount_text"] = value
            elif label.startswith("срок"):
                params["term_text"] = value
                evidence["term_text"] = value
            elif "базовая ставка" in label:
                params["base_rate_text"] = value
                evidence["base_rate_text"] = value
                params["base_rate_pct"] = _rate_json(value)
            elif any(k in label for k in ("ставк", "доходност", "доход в первые")) and "headline_rate_text" not in params:
                params["headline_rate_text"], params["headline_rate_label"] = value, adv["label"]
                evidence["headline_rate_text"] = value
                params["headline_rate_pct"] = _rate_json(value)
        # Доступность в ЛНР карточка не подтверждает; решает отдельная проверка (этап 3).
        return ExtractedProduct(
            name=canonical_name(title),
            category=category,
            params=params,
            evidence=evidence,
            lnr_status=AvailabilityStatus.NOT_CONFIRMED,
            lnr_quote=None,
        )
