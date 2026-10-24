"""Адаптер ПСБ (psbank.ru).

Страницы вкладов, накопительных счетов и «спецпредложений» собраны из одинаковых
карточек `.product-card` (проверено на документах от 24.10.2026). Адаптер извлекает
значения ДОСЛОВНО (как напечатано на сайте) и добавляет производные числа, которые
можно получить однозначно. Если на сайте вёрстка изменилась и карточек нет — это
сигнал об ошибке разбора, а не «нет продуктов» (см. ParseError).
"""

import re
from decimal import Decimal
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from bankintel.domain.enums import AvailabilityStatus, ProductCategory
from bankintel.sources.base import (
    BankAdapter,
    ExtractedProduct,
    FetchedDocument,
    SourceRef,
    register_adapter,
)

_NUM = r"\d+(?:[.,]\d+)?"
_NAME_IN_QUOTES = re.compile(r"«([^»]+)»")
_CURRENCY = {"₽": "RUB", "¥": "CNY", "$": "USD", "€": "EUR"}


class ParseError(Exception):
    """Страница получена, но ожидаемой структуры в ней нет."""


def _clean(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())
    return text or None


def parse_rate_range(text: str) -> tuple[Decimal | None, Decimal | None] | None:
    """'От 16% до 20%' -> (16, 20); 'До 16% годовых' -> (None, 16); '28,0%' -> (28.0, 28.0).
    Возвращает None, если однозначно разобрать нельзя."""
    t = text.replace("\xa0", " ").lower()
    nums = [Decimal(n.replace(",", ".")) for n in re.findall(_NUM, t)]
    if not nums or "%" not in t:
        return None
    if t.startswith("до") and len(nums) == 1:
        return None, nums[0]
    if t.startswith("от") and len(nums) == 1:
        return nums[0], None
    if len(nums) == 1:
        return nums[0], nums[0]
    if len(nums) == 2:
        return min(nums), max(nums)
    return None


def _currency(text: str) -> str | None:
    for sym, code in _CURRENCY.items():
        if sym in text:
            return code
    return None


def canonical_name(title: str) -> str:
    m = _NAME_IN_QUOTES.search(title)
    return m.group(1).strip() if m else title.strip()


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


def _rate_json(text: str) -> dict | None:
    r = parse_rate_range(text)
    if r is None:
        return None
    return {"min": str(r[0]) if r[0] is not None else None, "max": str(r[1]) if r[1] is not None else None}
