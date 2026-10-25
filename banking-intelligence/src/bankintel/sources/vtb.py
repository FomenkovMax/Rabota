"""Адаптер ВТБ (vtb.ru), страница «Вклады и счета».

Вёрстка на styled-components: классы хешированные (`...__Box-...-sc-14qzghz-0 gdSSlN`),
поэтому опираемся на устойчивые префиксы имён компонентов (`card-widestyles__CardTemplate`,
`TitleLinkWrapper`, `markdown-numbers`), а не на хеши. Проверено на документе от 24.10.2026.
На одной странице лежат и вклады, и накопительные счета — категорию определяем по карточке.
"""

import re
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
from bankintel.sources.common import FAQ_PREFIX, ParseError, canonical_name, clean_text, detect_currency, rate_json

_PRODUCT_PATH = "/personal/vklady-i-scheta/"
_ACCOUNT_RE = re.compile(r"сч[её]т", re.I)
_QUESTION = '[itemtype$="schema.org/Question"]'
# Блок с таким «вопросом» — навигация по продуктам банка, а не условия.
_NOT_CONDITIONS = {"вам может быть интересно"}
# Листовые текстовые блоки ответа: абзацы markdown и пункты списков.
_BLOCKS = 'li, [class*="markdown-paragraph"], p'


def _text(node: Tag) -> str:
    """Текст блока как на странице: узлы склеиваются без добавленных пробелов (иначе «На сайте :»,
    «легко» ) — проверено на 1438 блоках), а перенос строки <br> заменяется пробелом."""
    for br in node.find_all("br"):
        br.replace_with(" ")
    return " ".join(node.get_text("").replace("\xa0", " ").split())


def _answer_lines(answer: Tag) -> list[str]:
    lines = []
    for block in answer.select(_BLOCKS):
        if block.select(_BLOCKS):
            continue  # вложенный блок: берём листья, чтобы не дублировать текст
        if text := _text(block):
            lines.append(text)
    return lines or ([_text(answer)] if _text(answer) else [])


def _category(title: str, labels: list[str], description: str | None) -> ProductCategory:
    if _ACCOUNT_RE.search(title) or any("период действия счета" in lb for lb in labels):
        return ProductCategory.SAVINGS
    if "срок" not in labels and description and description.lower().startswith("счет"):
        return ProductCategory.SAVINGS
    return ProductCategory.DEPOSIT


@register_adapter("vtb")
class VtbAdapter(BankAdapter):
    SOURCE_KEYS = {"deposits"}

    def parse_detail(self, source: SourceRef, doc: FetchedDocument) -> list[ConditionRow]:
        """Страница продукта: блоки «вопрос — ответ» (schema.org/Question), дословно.

        Страницы ВТБ разнородны (проверено на 12 страницах 24.10.2026): условия — свободный текст в
        FAQ, общих заголовков нет. Поэтому правила только сохраняют пары «вопрос → ответ» как есть, без
        разбора на поля (срок, сумма, пополнение и т.п. извлекает этап 3: AI + проверка цитат).
        Подпись начинается с «Вопрос: » — мониторинг считает их изменения справочными.
        """
        soup = BeautifulSoup(doc.content, "html.parser")
        items = soup.select(_QUESTION)
        if not items:
            raise ParseError(f"{source.key}: на странице продукта нет блоков «вопрос — ответ» (вёрстка изменилась?)")
        rows: list[ConditionRow] = []
        seen: dict[str, str] = {}
        for item in items:
            question = clean_text(item.select_one('[itemprop="name"]'))
            answer = item.select_one('[itemprop="text"]')
            if not question or answer is None or question.lower() in _NOT_CONDITIONS:
                continue
            value = "\n".join(_answer_lines(answer))
            if not value:
                continue
            label = FAQ_PREFIX + question
            if seen.get(label) == value:
                continue  # тот же блок повторён на странице (например, для другой версии вёрстки)
            if label in seen:  # одинаковый вопрос с разным ответом: сохраняем оба, ключ различаем номером
                n = sum(1 for r in rows if r.label == label or r.label.startswith(label + " (")) + 1
                label = f"{label} ({n})"
            seen[label] = value
            rows.append(ConditionRow(label, value))
        if not rows:
            raise ParseError(f"{source.key}: блоки «вопрос — ответ» есть, но ни одного с текстом ответа")
        return rows

    def parse(self, source: SourceRef, doc: FetchedDocument) -> list[ExtractedProduct]:
        if source.key not in self.SOURCE_KEYS:
            return []
        soup = BeautifulSoup(doc.content, "html.parser")
        cards = soup.select('[class*="card-widestyles__CardTemplate"]')
        if not cards:
            raise ParseError(f"{source.key}: на странице нет карточек card-wide (вёрстка изменилась?)")
        products, seen = [], set()
        for card in cards:
            p = self._parse_card(card, source, doc)
            if p and (p.category, p.name) not in seen:
                seen.add((p.category, p.name))
                products.append(p)
        if not products:
            raise ParseError(f"{source.key}: карточки есть, но ни одного продукта с названием и ставкой")
        return products

    def _parse_card(self, card: Tag, source: SourceRef, doc: FetchedDocument) -> ExtractedProduct | None:
        advantages = []
        for n in card.select('[class*="markdown-numbers"]'):
            value, label = clean_text(n.select_one("p")), clean_text(n.select_one("span"))
            if value:
                advantages.append({"value": value, "label": label or ""})
        if not advantages:
            return None  # промо-блок без цифр, не продукт

        title_link = card.select_one('a[class*="TitleLinkWrapper"]')
        title = clean_text(title_link)
        if not title:  # запасной вариант: alt картинки карточки — тоже реальный текст страницы
            img = card.select_one("img[alt]")
            title = (img.get("alt") or "").strip() if img else None
        if not title:
            return None
        href = title_link.get("href") if title_link and title_link.get("href") else None
        if not href:
            href = next((a["href"] for a in card.select("a[href]") if _PRODUCT_PATH in a["href"]), None)
        if href and not href.startswith(("/", "http")):
            href = "/" + href

        description = None
        for p in card.select('[class*="markdown-paragraph"]'):
            if not p.select('[class*="markdown-numbers"]') and clean_text(p):
                description = clean_text(p)
                break

        labels = [a["label"].lower() for a in advantages]
        params: dict = {
            "kind": "card",
            "page_key": source.key,
            "title": title,
            "product_url": urljoin(doc.url, href) if href else None,
            "description": description,
            "advantages": advantages,
        }
        evidence = {"title": title}
        for adv in advantages:
            label, value = adv["label"].lower(), adv["value"]
            if label.startswith("сумма"):
                params["amount_text"] = value
                evidence["amount_text"] = value
            elif label.startswith("срок"):
                params["term_text"] = value
                evidence["term_text"] = value
            elif label.startswith("доходность"):
                params["yield_text"], params["yield_pct"] = value, rate_json(value)
                evidence["yield_text"] = value
            elif label.startswith("ставка") and "headline_rate_text" not in params:
                params["headline_rate_text"], params["headline_rate_label"] = value, adv["label"]
                params["headline_rate_pct"] = rate_json(value)
                evidence["headline_rate_text"] = value
        if "headline_rate_text" not in params:
            return None  # без ставки сравнивать нечего; не угадываем
        params["currency"] = next((c for a in advantages if (c := detect_currency(a["value"]))), None)
        # Доступность в ЛНР карточка не подтверждает (проверено: на странице ЛНР не упомянута).
        return ExtractedProduct(
            name=canonical_name(title),
            category=_category(title, labels, description),
            params=params,
            evidence=evidence,
            lnr_status=AvailabilityStatus.NOT_CONFIRMED,
            lnr_quote=None,
        )
