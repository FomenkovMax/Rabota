"""Адаптер ЦМРБанка (cmrbank.ru).

Данные продуктов лежат в самой странице как JSON внутри inline-скрипта калькулятора (`deposites: {...}`), а не в видимом HTML
и не в отдельных запросах: Playwright для сбора НЕ нужен. Таблицы ставок нормализуются, логику выбора ставки портирует
`analytics.rate_tables.lookup` (сверена с настоящим калькулятором по эталону из Playwright — tools/cmr_calculator_golden.py).
Пока на сайте не изменится структура JSON — разбор детерминирован; иначе — ParseError (а не «нет продуктов»).
"""

import json
import re
from decimal import Decimal

from bankintel.analytics.rate_tables import max_rate
from bankintel.domain.enums import AvailabilityStatus, ProductCategory
from bankintel.sources.base import BankAdapter, ExtractedProduct, FetchedDocument, SourceRef, register_adapter
from bankintel.sources.common import ParseError

BASE = "https://www.cmrbank.ru"
TYPE_TO_CATEGORY = {"deposit": ProductCategory.DEPOSIT, "account": ProductCategory.SAVINGS}
_PREFIX = re.compile(r"^(Вклад|Накопительный счет)\s+")
_VARIABLE = re.compile(r"по вкладу\s*[«\"]([^»\"]+)[»\"]\s*\(вклад с переменной", re.I)


def extract_js_object(html: str, key: str) -> dict:
    """Достаёт JSON-объект `key: {...}` из inline-скрипта: сканирование скобок с учётом строк (без eval и без regexp по JSON)."""
    i = html.find(f"{key}:")
    if i < 0:
        raise ParseError(f"в странице нет данных «{key}» (структура сайта изменилась?)")
    start = html.find("{", i)
    if start < 0:
        raise ParseError(f"«{key}»: нет объекта")
    depth, in_str, esc = 0, False, False
    for pos in range(start, len(html)):
        c = html[pos]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : pos + 1])
                except json.JSONDecodeError as exc:
                    raise ParseError(f"«{key}»: некорректный JSON ({exc.msg})") from None
    raise ParseError(f"«{key}»: не закрыта скобка")


def _ids(mapping: dict) -> list[str]:
    return sorted(mapping, key=lambda k: int(k))  # JS перебирает целочисленные ключи по возрастанию


def _rate(container, term_id: str) -> str | None:
    """Ставка по id срока: контейнер бывает словарём или списком (PHP -> JSON); пусто, '' и 0 — ставки нет."""
    value = None
    if isinstance(container, dict):
        value = container.get(term_id)
    elif isinstance(container, list) and term_id.isdigit() and int(term_id) < len(container):
        value = container[int(term_id)]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return str(Decimal(str(value)))


def build_rate_table(p: dict) -> dict:
    sums, terms, rates = p.get("sums") or {}, p.get("terms") or {}, p.get("rates") or {}
    if not sums or not terms or not rates:
        raise ParseError(f"{p.get('name')}: нет таблиц сумм/сроков/ставок")
    fixed = not p.get("max_term")
    tiers = []
    for sid in _ids(sums):
        r = rates.get(sid)
        if r is None:
            continue
        group = "salary_card_off" if r.get("salary_card") else "salary_card_disable"  # без зарплатной карты и без льгот
        tiers.append({
            "id": sid, "min_sum": sums[sid], "replenish": bool(r.get("replenish")), "withdraw": bool(r.get("withdraw")),
            "terms": [{"id": tid, "days": terms[tid], "at_end": _rate((r.get("pct_at_and") or {}).get(group), tid),
                       "monthly": _rate((r.get("pct_at_month") or {}).get(group), tid)} for tid in _ids(terms)],
        })
    return {"fixed_terms": fixed, "min_term": min(terms.values()), "max_term": max(terms.values()) if fixed else p["max_term"], "tiers": tiers}


def money_text(x) -> str:
    return f"{int(x):,}".replace(",", " ") + " руб."


def rate_text(x: Decimal) -> str:
    return f"До {str(x).replace('.', ',')} %"


@register_adapter("cmr")
class CmrAdapter(BankAdapter):
    PAGE_DEFAULTS = {"deposits": ProductCategory.DEPOSIT, "savings_accounts": ProductCategory.SAVINGS}

    def parse(self, source: SourceRef, doc: FetchedDocument) -> list[ExtractedProduct]:
        if source.key not in self.PAGE_DEFAULTS:
            return []
        html = doc.content.decode("utf-8", errors="replace")
        data = extract_js_object(html, "deposites")
        variable = {m.lower() for m in _VARIABLE.findall(html)}
        products = []
        for pid in _ids(data):
            p = data[pid]
            if str(p.get("is_active")) != "1":
                continue
            category = TYPE_TO_CATEGORY.get(p.get("type"))
            if category is None:
                raise ParseError(f"{p.get('name')}: неизвестный тип «{p.get('type')}»")
            table = build_rate_table(p)
            top = max_rate(table)
            if top is None:
                continue  # нет ни одной действующей ставки
            title = p["name"].replace("\\", "")
            name = _PREFIX.sub("", title).replace('"', "").strip()  # «Доход на максимум для пенсионеров» остаётся отдельным продуктом
            min_sum = min(t["min_sum"] for t in table["tiers"])
            terms_days = [e["days"] for e in table["tiers"][0]["terms"]]
            quoted = re.findall(r'"([^"]+)"', title)
            params = {
                "kind": "card", "page_key": source.key, "title": title, "source_id": pid, "product_url": None,
                "description": (p.get("annotation") or "").strip() or None,
                "conditions_pdf": f"{BASE}{p['pdf_file_path']}" if p.get("pdf_file_path") else None,
                "headline_rate_text": rate_text(top), "headline_rate_pct": {"min": None, "max": str(top)},
                "amount_text": f"От {money_text(min_sum)}", "currency": "RUB", "term_text": f"От {min(terms_days)} дн.",
                "max_sum": p.get("max_sum") or None, "has_replenish": any(t["replenish"] for t in table["tiers"]),
                "has_withdraw": any(t["withdraw"] for t in table["tiers"]), "rate_table": table,
                "floating_rate": bool(quoted and quoted[0].lower() in variable),
            }
            products.append(ExtractedProduct(
                name=name, category=category, params=params,
                evidence={"title": title, "headline_rate_text": f"максимум по таблице ставок страницы: {top} %"},
                lnr_status=AvailabilityStatus.NOT_CONFIRMED, lnr_quote=None,
            ))
        if not products:
            raise ParseError(f"{source.key}: в данных страницы нет действующих продуктов")
        return products
