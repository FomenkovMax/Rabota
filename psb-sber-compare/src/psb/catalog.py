"""Каталог розничных продуктов ПСБ из карты сайта.

Карта сайта приезжает в SSR-состоянии любой страницы по ключу `/Site/structure`
— примерно 2800 узлов дерева. Нам нужна только розница и акции, поэтому
обход ограничен заданными разделами: полный обход — это сотни запросов,
а данные лежат всё равно в продуктовых разделах.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from .state import extract_state, find_entries

log = logging.getLogger(__name__)

# Разделы розницы: alias → человекочитаемая категория.
# Список сознательно ручной: автоматический отбор «всё под /personal»
# затянул бы служебные страницы (cookies, 115-ФЗ, согласия на обработку).
RETAIL_SECTIONS: dict[str, str] = {
    "loans": "Кредиты",
    "mortgage": "Ипотека",
    "creditcards": "Кредитные карты",
    "debetcards": "Дебетовые карты",
    "cards": "Банковские карты",
    "saving": "Вклады",
    "savingsaccount": "Накопительные счета",
    "salary": "Зарплатные карты",
    "pensioncards": "Пенсионные карты",
    "pensioners": "Пенсионные продукты",
    "insurance": "Страхование",
    "premium": "Премиальное обслуживание",
    "pds": "Долгосрочные сбережения",
    "ecommerce": "Счета и переводы",
    "savingsoffers": "Специальные предложения",
}

# Страницы-акции разбросаны по всему /personal, а не лежат в одном разделе,
# поэтому ловим их по заголовку.
PROMO_TITLE_RE = re.compile(r"акци[яию]|кешб[эе]к|кэшб[эе]к|спецпредложени", re.I)

# Служебное, что не является продуктом даже внутри продуктового раздела.
SKIP_ALIAS_RE = re.compile(
    r"^(thanks|cookies|not_found|agreement|documents|archivedoc|release\d*|"
    r"nikita|dm\d+|faq|calculator|methods|guide|taxes|automatic-repayment)",
    re.I,
)


@dataclass
class CatalogPage:
    """Страница-кандидат на разбор."""

    url_path: str          # /personal/loans/kredit-nalichnymi
    title: str
    category: str          # «Кредиты»
    section: str           # loans
    node_id: int | None = None
    is_promo: bool = False
    breadcrumbs: list[str] = field(default_factory=list)


def _walk(node: dict[str, Any], trail: list[str], titles: list[str]) -> Iterator[tuple[list[str], list[str], dict]]:
    alias = node.get("alias") or ""
    title = (node.get("details") or {}).get("title", {}).get("value") or alias
    path = trail + [alias] if alias else trail
    names = titles + [title] if alias else titles
    yield path, names, node
    for child in node.get("children") or []:
        yield from _walk(child, path, names)


def build_catalog(page_html: str, *, include_promos: bool = True) -> list[CatalogPage]:
    """Строит список страниц для обхода из любой страницы сайта."""
    state = extract_state(page_html)
    structures = find_entries(state, "/Site/structure")
    if not structures:
        log.error("В состоянии страницы нет /Site/structure — каталог не построить")
        return []

    pages: list[CatalogPage] = []
    seen: set[str] = set()

    for path, names, node in _walk(structures[0], [], []):
        # path выглядит как ['main', 'personal', 'loans', 'kredit-nalichnymi']
        if len(path) < 3 or path[0] != "main" or path[1] != "personal":
            continue

        section = path[2]
        alias = path[-1]
        if SKIP_ALIAS_RE.match(alias):
            continue

        title = names[-1] if names else alias
        url_path = "/" + "/".join(path[1:])  # /main отбрасываем: в URL его нет
        if url_path in seen:
            continue

        is_promo = bool(PROMO_TITLE_RE.search(title))
        in_section = section in RETAIL_SECTIONS

        if not in_section and not (include_promos and is_promo):
            continue

        # Узлы, которые сами по себе не страницы (скрытые/несуществующие),
        # CMS помечает флагом ispage.
        details = node.get("details") or {}
        if details.get("ispage", {}).get("value") is False:
            continue

        seen.add(url_path)
        pages.append(
            CatalogPage(
                url_path=url_path,
                title=title,
                category=RETAIL_SECTIONS.get(section, "Акции и спецпредложения"),
                section=section,
                node_id=node.get("id"),
                is_promo=is_promo,
                breadcrumbs=names[1:],
            )
        )

    log.info("Каталог: %s страниц (%s акций)", len(pages), sum(p.is_promo for p in pages))
    return pages
