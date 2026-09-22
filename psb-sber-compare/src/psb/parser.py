"""Извлечение условий продукта из SSR-состояния страницы ПСБ.

Условия лежат в нескольких типах контента CMS, каждый со своей структурой:

  getTariffTableRows        таблица «параметр → значение»: Ставка, ПСК, Сумма,
                            Срок, Пеня, Подтверждение дохода. Главный источник.
  tableData?id=...          таблицы ставок по вкладам (срок × сумма).
  BannerItems               шапка продукта: «от 16,9%», «до 5 млн ₽».
  ProductNotificationBanner промо-плашка — как правило, действующая акция.
  BenefitItems              преимущества; иногда содержат условия акции.

Числа приводим к float, но исходную строку сохраняем всегда: для отчёта
топ-менеджеру важно показать формулировку банка дословно, а не только цифру.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .state import clean, extract_state, find_entries

log = logging.getLogger(__name__)

# --- нормализация чисел ---------------------------------------------------

_RATE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,3})?)\s*%")
_CURRENCY_RE = re.compile(r"₽|руб|рублей|р\.", re.I)
_NUMBER_RE = re.compile(r"\d[\d\s\u00a0]*(?:[.,]\d+)?")

_MULTIPLIER = {"млрд": 1e9, "млн": 1e6, "тыс": 1e3, "тысяч": 1e3}
_UNIT_RE = re.compile(r"млрд|млн|тыс(?:яч)?", re.I)
_TERM_UNIT_RE = re.compile(r"лет|год[а]?|мес(?:яц[аев]*)?|дн[ейя]", re.I)


def parse_rates(text: str) -> list[float]:
    """Все процентные значения из строки, в порядке появления."""
    return [float(m.group(1).replace(",", ".")) for m in _RATE_RE.finditer(text)]


def _numbers_with_units(text: str, unit_re: re.Pattern[str]) -> list[tuple[float, str, bool]]:
    """Числа строки вместе с относящейся к ним единицей измерения.

    В формулировках ПСБ единица часто указана только у последнего числа
    диапазона: «От 100 000 — 5 000 000 ₽», «От 36 до 84 месяцев». Наивный
    разбор теряет нижнюю границу, поэтому число без своей единицы наследует
    единицу ближайшего следующего числа.
    """
    found: list[tuple[float, str | None]] = []
    matches = list(_NUMBER_RE.finditer(text))

    for index, match in enumerate(matches):
        raw = match.group().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        # Хвост до следующего числа — там и стоит единица, если она есть.
        tail_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tail = text[match.end():tail_end]
        unit_match = unit_re.search(tail)
        found.append((value, unit_match.group().lower() if unit_match else None))

    # Протягиваем единицу справа налево, помечая унаследованные случаи:
    # вызывающий код сам решает, доверять наследованию или нет.
    resolved: list[tuple[float, str, bool]] = []
    inherited = ""
    for value, unit in reversed(found):
        if unit:
            inherited = unit
            resolved.append((value, unit, False))
        else:
            resolved.append((value, inherited, True))
    resolved.reverse()
    return resolved


def parse_money(text: str) -> list[float]:
    """Денежные суммы в рублях с учётом «млн»/«тыс» и диапазонов."""
    if not _CURRENCY_RE.search(text):
        return []
    out: list[float] = []
    for value, unit, is_inherited in _numbers_with_units(text, _UNIT_RE):
        # «От 30 000 до 1,5 млн ₽»: у 30 000 своей единицы нет, но множитель
        # чужой ему не подходит — сумма уже записана полностью. Наследуем
        # множитель только для сокращённой записи (числа меньше тысячи).
        if is_inherited and value >= 1000:
            unit = ""
        multiplier = 1.0
        for key, factor in _MULTIPLIER.items():
            if unit.startswith(key):
                multiplier = factor
                break
        amount = value * multiplier
        # Отсекаем годы, номера сносок и проценты, попавшие в строку с ₽.
        if amount >= 1000:
            out.append(amount)
    return out


def parse_term_months(text: str) -> list[int]:
    """Сроки, приведённые к месяцам, с учётом диапазонов."""
    out: list[int] = []
    for value, unit, _inherited in _numbers_with_units(text, _TERM_UNIT_RE):
        if not unit:
            continue
        if unit.startswith(("лет", "год")):
            out.append(int(value * 12))
        elif unit.startswith("мес"):
            out.append(int(value))
        elif unit.startswith("дн"):
            out.append(max(1, round(value / 30)))
    return out


# --- модель продукта ------------------------------------------------------

@dataclass
class Promo:
    """Действующая акция/спецпредложение."""

    title: str
    text: str = ""
    url: str = ""
    source_path: str = ""
    content_type: str = ""

    def key(self) -> str:
        return f"{self.title}|{self.text}"[:400]


@dataclass
class Product:
    """Нормализованные условия одного продукта ПСБ."""

    bank: str = "ПСБ"
    url_path: str = ""
    title: str = ""
    category: str = ""
    section: str = ""
    region: str = ""

    # Ключевой параметр для светофора.
    rate_min: float | None = None
    rate_max: float | None = None
    rate_raw: str = ""

    # Полная стоимость кредита.
    apr_min: float | None = None
    apr_max: float | None = None
    apr_raw: str = ""

    amount_min: float | None = None
    amount_max: float | None = None
    amount_raw: str = ""

    term_min_months: int | None = None
    term_max_months: int | None = None
    term_raw: str = ""

    # Условия, при которых достигается максимальная ставка: срок и сумма.
    # Без них витринная ставка вводит в заблуждение.
    rate_conditions: str = ""

    # Всё, что банк указал в тарифной таблице, дословно.
    terms: dict[str, str] = field(default_factory=dict)
    promos: list[Promo] = field(default_factory=list)

    # Для ссылки на источник в отчёте.
    source_url: str = ""
    collected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["promos"] = [asdict(p) for p in self.promos]
        return data

    def fingerprint(self) -> str:
        """Слепок значимых условий — по нему ловим изменения между неделями."""
        parts = [
            self.rate_raw, self.apr_raw, self.amount_raw, self.term_raw,
            "|".join(f"{k}={v}" for k, v in sorted(self.terms.items())),
        ]
        return "␟".join(parts)


# --- извлечение -----------------------------------------------------------

# Как называются строки тарифной таблицы у ПСБ. Сопоставляем по подстроке,
# потому что формулировки гуляют: «Ставка», «Процентная ставка», «Ставка, %».
_FIELD_MATCHERS: list[tuple[str, re.Pattern[str]]] = [
    ("rate", re.compile(r"^(процентн\w*\s+)?ставка", re.I)),
    ("apr", re.compile(r"полная стоимост", re.I)),
    ("amount", re.compile(r"сумма\s+(кредита|займа|вклада)?|размер\s+кредита", re.I)),
    ("term", re.compile(r"срок\s+(кредита|вклада|договора)?", re.I)),
]


def _match_field(label: str) -> str | None:
    for name, pattern in _FIELD_MATCHERS:
        if pattern.search(label):
            return name
    return None


def _span(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return min(values), max(values)


def _extract_tariff_rows(state: dict[str, Any], product: Product) -> None:
    """Главный источник: таблица «параметр → значение»."""
    for entry in find_entries(state, "getTariffTableRows"):
        rows = (entry or {}).get("tariffTableRowsResult") or []
        for row in sorted(rows, key=lambda r: r.get("order", 0)):
            label = clean(row.get("column1"))
            value = clean(row.get("column2"))
            if not label or not value:
                continue
            product.terms.setdefault(label, value)

            field_name = _match_field(label)
            if field_name == "rate" and not product.rate_raw:
                product.rate_raw = value
                product.rate_min, product.rate_max = _span(parse_rates(value))
            elif field_name == "apr" and not product.apr_raw:
                product.apr_raw = value
                product.apr_min, product.apr_max = _span(parse_rates(value))
            elif field_name == "amount" and not product.amount_raw:
                product.amount_raw = value
                product.amount_min, product.amount_max = _span(parse_money(value))
            elif field_name == "term" and not product.term_raw:
                product.term_raw = value
                months = parse_term_months(value)
                if months:
                    product.term_min_months, product.term_max_months = min(months), max(months)


# Таблица «минимальная гарантированная ставка» (МГС) — это другая метрика,
# по закону она считается иначе и всегда ниже витринной. Смешивать её со
# ставкой нельзя: диапазон разъезжается и цифра в отчёте становится неверной.
_GUARANTEED_RE = re.compile(r"гарантирован", re.I)
_PERCENT_IN_CELL_RE = re.compile(r"\d\s*%")


def _table_cells(row: dict[str, Any]) -> list[str]:
    cells = sorted(row.get("cells") or [], key=lambda c: c.get("order", 0))
    return [clean(c.get("content")) for c in cells]


def _rates_from_table(table: dict[str, Any]) -> list[tuple[float, str, str]]:
    """Ставки вклада вместе с условиями: (ставка, срок, сумма).

    Условия нужны не для украшения. Ставка 31% годовых выглядит совсем
    иначе, когда рядом написано «32 дня, от 10 000 до 50 000 ₽»: без этого
    акционный вклад сравнивается с обычным срочным как равный.

    МГС отсеиваем по строке и колонке, а не по заголовку таблицы: в шапке
    ПСБ нередко перечислены обе метрики сразу, и фильтр по ней выбросил бы
    таблицу целиком вместе с настоящими ставками.
    """
    header_cells = _table_cells(table.get("headerRow") or {})
    data_rows = [_table_cells(row) for row in table.get("rows") or []]

    # Колонку со ставками определяем по содержимому, а не по названию.
    # Названия ненадёжны: у одного вклада колонки подписаны «Срок вклада
    # 32 дня», у другого просто «32 дня», а шапка «СУММА/СРОК ВКЛАДА»
    # ложно срабатывает на слово «срок» и выдаёт колонку сумм за колонку ставок.
    width = max([len(cells) for cells in data_rows] + [len(header_cells)] or [0])
    rate_columns = []
    for index in range(width):
        label = header_cells[index] if index < len(header_cells) else ""
        if _GUARANTEED_RE.search(label):
            continue
        has_percent = any(
            index < len(cells) and _PERCENT_IN_CELL_RE.search(cells[index])
            for cells in data_rows
        )
        if has_percent:
            rate_columns.append(index)

    info_columns = [i for i in range(width) if i not in rate_columns]

    found: list[tuple[float, str, str]] = []
    for row in table.get("rows") or []:
        cells = _table_cells(row)
        row_title = clean(row.get("title"))
        if _GUARANTEED_RE.search(row_title) or (cells and _GUARANTEED_RE.search(cells[0])):
            continue

        # Ячейки вне колонок со ставками описывают условия: сумму, категорию.
        if info_columns:
            amount = " – ".join(cells[i] for i in info_columns
                                if i < len(cells) and cells[i])
        else:
            amount = cells[0] if cells else ""

        indices = rate_columns or range(len(cells))
        for index in indices:
            if index >= len(cells):
                continue
            term = header_cells[index] if index < len(header_cells) else ""
            for rate in parse_rates(cells[index]):
                found.append((rate, term, amount))
    return found


def _extract_deposit_tables(state: dict[str, Any], product: Product) -> None:
    """Вклады: ставки лежат в сетке «срок × сумма», а не в тарифных строках."""
    if product.rate_raw:
        return

    found: list[tuple[float, str, str]] = []
    for entry in find_entries(state, "tableData?id="):
        if isinstance(entry, dict):
            found.extend(_rates_from_table(entry))

    # Отсекаем заведомо не-ставки: доли процента из сносок и всё выше 100.
    found = [item for item in found if 0.1 <= item[0] <= 100]
    if not found:
        return

    rates = [item[0] for item in found]
    product.rate_min, product.rate_max = min(rates), max(rates)
    product.rate_raw = (f"от {product.rate_min:.2f}% до {product.rate_max:.2f}%"
                        .replace(".", ","))
    product.terms.setdefault("Ставка (из таблицы вкладов)", product.rate_raw)

    best_rate, best_term, best_amount = max(found, key=lambda item: item[0])
    conditions = ", ".join(part for part in (best_term, best_amount) if part)
    if conditions:
        product.rate_conditions = f"{best_rate:.2f}%".replace(".", ",") + f" — {conditions}"
        product.terms.setdefault("Условия максимальной ставки", product.rate_conditions)

    # Срок и сумму берём из той же строки, если отдельно их не нашли.
    if not product.term_raw and best_term:
        months = parse_term_months(best_term)
        if months:
            product.term_min_months, product.term_max_months = min(months), max(months)
            product.term_raw = best_term
    if not product.amount_raw and best_amount:
        amounts = parse_money(best_amount)
        if amounts:
            product.amount_min, product.amount_max = min(amounts), max(amounts)
            product.amount_raw = best_amount


def _extract_banner(state: dict[str, Any], product: Product) -> None:
    """Шапка продукта: подстраховка, если тарифной таблицы на странице нет."""
    for entry in find_entries(state, "BannerItems"):
        for item in (entry or {}).get("bannerItems") or []:
            headline = clean(item.get("title"))
            advantages = clean(item.get("advantages"))
            description = clean(item.get("description"))
            combined = " ".join(x for x in (headline, advantages, description) if x)
            if not combined:
                continue

            product.terms.setdefault("Баннер продукта", combined[:500])

            if not product.rate_raw:
                rates = parse_rates(combined)
                if rates:
                    product.rate_min, product.rate_max = min(rates), max(rates)
                    product.rate_raw = combined[:200]
            if not product.amount_raw:
                amounts = parse_money(combined)
                if amounts:
                    product.amount_min, product.amount_max = min(amounts), max(amounts)
                    product.amount_raw = combined[:200]
            if not product.term_raw:
                months = parse_term_months(combined)
                if months:
                    product.term_min_months, product.term_max_months = min(months), max(months)
                    product.term_raw = combined[:200]


# Признаки того, что плашка — реально действующее предложение, а не просто
# рекламный слоган. Без фильтра в акции попадают «Деньги в безопасности»
# и прочие лозунги, которые сравнивать со Сбером бессмысленно.
_PROMO_SIGNAL_RE = re.compile(
    r"акци|кешб[эе]к|кэшб[эе]к|скидк|снизим|снижен|бонус|дарим|подар|"
    r"приз|выигр|бесплатн|вернем|вернём|возврат|повышенн|\d+\s*%|"
    r"до\s+\d{1,2}[.\s]\d{2}[.\s]\d{2,4}",
    re.I,
)


def _is_real_promo(text: str) -> bool:
    return bool(text) and bool(_PROMO_SIGNAL_RE.search(text))


def _extract_promos(state: dict[str, Any], product: Product) -> None:
    """Акции: промо-плашка продукта и явно акционные преимущества."""
    seen: set[str] = set()

    def add(promo: Promo) -> None:
        if not _is_real_promo(f"{promo.title} {promo.text}"):
            return
        if promo.key() in seen:
            return
        seen.add(promo.key())
        product.promos.append(promo)

    for entry in find_entries(state, "ProductNotificationBanner"):
        banner = (entry or {}).get("productNotificationBanner") or {}
        title = clean(banner.get("title"))
        if not title:
            continue
        link = banner.get("link") or {}
        add(Promo(
            title=title,
            text=clean(banner.get("text")),
            url=link.get("url") or "",
            source_path=product.url_path,
            content_type="ProductNotificationBanner",
        ))

    for entry in find_entries(state, "InfolineItems"):
        for item in (entry or {}).get("infolineItems") or []:
            text = clean(item.get("text")) or clean(item.get("title"))
            if text:
                add(Promo(title=text[:250], source_path=product.url_path,
                          content_type="InfolineItems"))

    # Страница, которая сама является акцией: её заголовок и баннер — и есть
    # условие предложения.
    if getattr(product, "_is_promo_page", False):
        for entry in find_entries(state, "BannerItems"):
            for item in (entry or {}).get("bannerItems") or []:
                headline = clean(item.get("title")) or product.title
                body = clean(item.get("description"))
                add(Promo(
                    title=headline[:250],
                    text=body[:500],
                    url=product.source_url,
                    source_path=product.url_path,
                    content_type="PromoPage",
                ))


def parse_product(page_html: str, page: Any, region_name: str, collected_at: str) -> Product:
    """Собирает Product со страницы. `page` — CatalogPage."""
    state = extract_state(page_html)

    product = Product(
        url_path=page.url_path,
        title=clean(page.title),
        category=page.category,
        section=page.section,
        region=region_name,
        source_url=f"https://www.psbank.ru{page.url_path}",
        collected_at=collected_at,
    )

    # Флаг нужен извлечению акций: на странице-акции сам баннер и есть оффер.
    object.__setattr__(product, "_is_promo_page", bool(getattr(page, "is_promo", False)))

    if not state:
        log.warning("Пустое состояние на %s — страница пропущена", page.url_path)
        return product

    _extract_tariff_rows(state, product)
    _extract_deposit_tables(state, product)
    _extract_banner(state, product)
    _extract_promos(state, product)

    return product
