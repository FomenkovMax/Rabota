"""ЦМРБанк: данные прямо из кода страниц, без браузера.

Сайт ЦМР рисует витрину вкладов скриптом, а сами условия лежат в коде
страницы готовым блоком: `deposites: {...}` на странице вкладов и
`credit: {...}` на странице каждого кредита — ставки по срокам и суммам,
пополнение, снятие, скидки за зарплатную карту и страховку. Браузерный
разбор видел вместо них шаблоны `{{ deposit.name }}` и находил один вклад
из шести. Карты — обычный текст страницы.

Защиты нет, поэтому хватает обычного запроса: быстрее, чем браузер, и не
тратит память сервера на Chromium.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from ..psb.parser import Product
from .base import BankAdapter, CollectResult, region_binding, registry

log = logging.getLogger(__name__)

BASE = "https://cmrbank.ru"
DEPOSITS = f"{BASE}/person/person-deposit/"
LOANS = f"{BASE}/person/person-loans/"
CARDS = f"{BASE}/person/card/"

#: Страницы внутри разделов, которые не продукты.
_SKIP = re.compile(r"restructuring|card-documents|mir-pay|deposit-calc|deposit-account", re.I)

_PAYOUT = {"pct_at_month": "выплата ежемесячно", "pct_at_and": "выплата в конце срока"}
_SALARY = {"salary_card_disable": "", "salary_card_on": "с зарплатной картой ЦМР",
           "salary_card_off": "без зарплатной карты"}


# --- разбор ---------------------------------------------------------------

def embedded_json(page: str, name: str) -> Any:
    """Блок данных `name: {...}` из скрипта страницы. None — если его нет."""
    match = re.search(rf"\b{re.escape(name)}\s*:\s*(?=[\[{{])", page)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(page, match.end())
    except json.JSONDecodeError:
        return None
    return value


def page_lines(page: str) -> list[str]:
    """Видимый текст страницы построчно — без скриптов и стилей."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"<(br|/tr|/div|/p|/h\d|/li|/td|/th)\b[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
    return [line for line in lines if line]


def _quotes(name: str) -> str:
    return re.sub(r'"([^"]+)"', r"«\1»", name or "").strip()


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _fmt(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def _months(days: int) -> int:
    return max(1, round(days / 30.4))


def deposit_rates(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Все ставки вклада: срок в днях, минимальная сумма, выплата, зарплатная карта."""
    terms = {str(k): int(v) for k, v in (item.get("terms") or {}).items()}
    sums = {str(k): float(v) for k, v in (item.get("sums") or {}).items()}
    out: list[dict[str, Any]] = []
    for sum_id, block in (item.get("rates") or {}).items():
        for payout_key, payout in _PAYOUT.items():
            for salary_key, salary in _SALARY.items():
                values = (block.get(payout_key) or {}).get(salary_key) or []
                pairs = (enumerate(values) if isinstance(values, list)
                         else values.items())
                for term_id, raw in pairs:
                    rate = _num(raw)
                    days = terms.get(str(term_id))
                    if rate is None or days is None:
                        continue
                    out.append({"rate": rate, "days": days, "min_sum": sums.get(str(sum_id)),
                                "payout": payout, "salary": salary})
    return out


def deposit_product(item: dict[str, Any], *, region: str, now: str) -> Product | None:
    rates = deposit_rates(item)
    name = _quotes(item.get("name", ""))
    if not name or str(item.get("is_active", "1")) == "0":
        return None
    category = "Накопительные счета" if item.get("type") == "account" else "Вклады"
    product = Product(
        bank="ЦМР", url_path=f"/person/person-deposit/#deposit-{item.get('id')}",
        title=name, category=category, region=region, source_url=DEPOSITS,
        collected_at=now,
    )
    if rates:
        best = max(rates, key=lambda r: r["rate"])
        product.rate_min = min(r["rate"] for r in rates)
        product.rate_max = best["rate"]
        product.rate_raw = f"до {_fmt(best['rate'])} %"
        parts = [f"{best['days']} дн."]
        if best["min_sum"]:
            parts.append(f"от {_money(best['min_sum'])}")
        parts.append(best["payout"])
        if best["salary"]:
            parts.append(best["salary"])
        product.rate_conditions = ", ".join(parts)
        days = sorted({r["days"] for r in rates})
        product.term_min_months, product.term_max_months = _months(days[0]), _months(days[-1])
        product.term_raw = (f"{days[0]} дн." if len(days) == 1
                            else f"от {days[0]} до {days[-1]} дн.")
        # Ставки по срокам без зарплатной карты — для сценариев «вклад на 6 мес».
        by_term: dict[int, float] = {}
        for r in rates:
            if r["salary"] != _SALARY["salary_card_on"]:
                by_term[r["days"]] = max(by_term.get(r["days"], 0), r["rate"])
        product.terms["Ставки по срокам"] = "; ".join(
            f"{d} дн. — {_fmt(v)} %" for d, v in sorted(by_term.items()))
    else:
        product.terms["Ставка"] = "на странице не указана"
    sums = [float(v) for v in (item.get("sums") or {}).values() if _num(v)]
    if sums:
        product.amount_min = min(sums)
    if _num(item.get("max_sum")):
        product.amount_max = float(item["max_sum"])
    if product.amount_min or product.amount_max:
        product.amount_raw = " ".join(filter(None, [
            f"от {_money(product.amount_min)}" if product.amount_min else "",
            f"до {_money(product.amount_max)}" if product.amount_max else ""]))
    flags = [r for r in (item.get("rates") or {}).values()]
    product.terms["Пополнение"] = "да" if any(f.get("replenish") for f in flags) else "нет"
    product.terms["Снятие"] = "да" if any(f.get("withdraw") for f in flags) else "нет"
    if item.get("annotation"):
        product.terms["Описание"] = item["annotation"]
    return product


_PSK = re.compile(r"полная стоимость кредита\s*([\d,]+)\s*%(?:\s*-\s*([\d,]+)\s*%)?", re.I)


def credit_product(page: str, url: str, *, region: str, now: str) -> Product | None:
    data = embedded_json(page, "credit")
    lines = page_lines(page)
    if not isinstance(data, dict) or not data.get("name"):
        return None
    values: list[float] = []
    for table in (data.get("rates") or {}).values():
        for row in table or []:
            values += [v for v in map(_num, row if isinstance(row, list) else [row]) if v]
    product = Product(
        bank="ЦМР", url_path=urlsplit(url).path, title=_quotes(data["name"]),
        category="Кредиты", region=region, source_url=url, collected_at=now,
    )
    if values:
        product.rate_min, product.rate_max = min(values), max(values)
        product.rate_raw = (f"{_fmt(product.rate_min)} % годовых" if product.rate_min == product.rate_max
                            else f"{_fmt(product.rate_min)}–{_fmt(product.rate_max)} % годовых")
    else:
        product.terms["Ставка"] = "на странице не указана"
    joined = "\n".join(lines)
    psk = _PSK.search(joined)
    if psk:
        low = float(psk.group(1).replace(",", "."))
        high = float(psk.group(2).replace(",", ".")) if psk.group(2) else low
        product.apr_min, product.apr_max, product.apr_raw = low, high, psk.group(0)
    if "Процентные ставки:" in lines:
        start = lines.index("Процентные ставки:") + 1
        conditions = [l for l in lines[start:start + 4] if "%" in l and "годовых" in l]
        product.rate_conditions = "; ".join(conditions)
        # У рефинансирования ставка для зарплатных клиентов есть только в
        # тексте: в блоке данных одна общая. Берём обе.
        listed = [float(v.replace(",", ".")) for v in
                  re.findall(r"(\d{1,2}(?:,\d{1,2})?)\s*%\s*годовых", " ".join(conditions))]
        if listed:
            product.rate_min = min([product.rate_min or listed[0]] + listed)
            product.rate_max = max([product.rate_max or listed[0]] + listed)
            product.rate_raw = (f"{_fmt(product.rate_min)}–{_fmt(product.rate_max)} % годовых"
                                if product.rate_min != product.rate_max
                                else f"{_fmt(product.rate_min)} % годовых")
    if _num(data.get("min_sum")):
        product.amount_min = float(data["min_sum"])
    if _num(data.get("max_sum")):
        product.amount_max = float(data["max_sum"])
    if product.amount_min or product.amount_max:
        product.amount_raw = f"от {_money(product.amount_min or 0)} до {_money(product.amount_max or 0)}"
    if _num(data.get("min_term")) and _num(data.get("max_term")):
        product.term_min_months, product.term_max_months = int(data["min_term"]), int(data["max_term"])
        product.term_raw = f"от {data['min_term']} до {data['max_term']} мес."
    if data.get("dscr"):
        product.terms["Описание"] = data["dscr"]
    return product


_BALANCE = re.compile(r"начисление процентов на остаток:?\s*\n?\s*([\d,]+)\s*%\s*годовых([^\n]*)", re.I)


def card_product(page: str, url: str, *, region: str, now: str) -> Product | None:
    lines = page_lines(page)
    crumb = next((l for l in lines if l.startswith("Главная страница /")), "")
    title = crumb.rsplit(" / ", 1)[-1].strip() if crumb else ""
    if not title or title == "Карты":
        return None
    product = Product(
        bank="ЦМР", url_path=urlsplit(url).path, title=title, category="Дебетовые карты",
        region=region, source_url=url, collected_at=now,
    )
    joined = "\n".join(lines)
    balance = _BALANCE.search(joined)
    if balance:
        rate = float(balance.group(1).replace(",", "."))
        product.rate_min = product.rate_max = rate
        product.rate_raw = f"{balance.group(1)}% годовых на остаток"
        product.rate_conditions = balance.group(2).strip(" ,.")
    cashback = [l for l in lines if l.lower().startswith("кешбэк ") and "%" in l]
    if cashback:
        product.terms["Кешбэк"] = "; ".join(dict.fromkeys(cashback))[:300]
    for label, pattern in (("Обслуживание", r"обслуживание карты|руб\. в год"),
                           ("Снятие в чужих банкоматах", r"^выдача наличных:"),
                           ("Переводы в другой банк по номеру карты",
                            r"цмр онлайн» в другой банк"),
                           ("СБП другому человеку", r"^другому человеку")):
        found = next((l for l in lines if re.search(pattern, l, re.I)), "")
        if found:
            product.terms[label] = found[:200]
    product.terms["Ставка"] = ("процент на остаток" if balance
                               else "процента на остаток нет")
    return product


def section_links(page: str, prefix: str) -> list[str]:
    """Ссылки на продукты внутри раздела: /person/card/<имя>/."""
    found = []
    for href in re.findall(r'href="([^"#?]+)"', page):
        path = urlsplit(urljoin(BASE, href)).path
        if (path.startswith(prefix) and path != prefix and path.count("/") == prefix.count("/") + 1
                and not _SKIP.search(path)):
            url = urljoin(BASE, path)
            if url not in found:
                found.append(url)
    return found


# --- адаптер ----------------------------------------------------------------

@registry.register
class CmrAdapter(BankAdapter):
    code = "cmr"
    title = "ЦМР"
    strategy = "обычные запросы: данные из кода страниц, без браузера"
    protection = ""
    verified = True

    def _get(self, session: requests.Session, url: str) -> str:
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = session.get(url, timeout=float(self.settings.get("timeout", 30)))
                response.raise_for_status()
                response.encoding = response.encoding or "utf-8"
                return response.text
            except requests.RequestException as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{url}: {last}")

    def collect(self) -> CollectResult:
        from ..psb.client import build_ca_bundle

        method, region = region_binding(False, self.settings)
        now = datetime.now().isoformat(timespec="seconds")
        pause = float(self.settings.get("pause", 1.0))
        session = requests.Session()
        session.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
        session.verify = build_ca_bundle()

        products: list[Product] = []
        failures: list[str] = []
        visited = 0

        try:
            page = self._get(session, DEPOSITS)
            visited += 1
            deposits = embedded_json(page, "deposites") or {}
            for item in (deposits.values() if isinstance(deposits, dict) else deposits):
                product = deposit_product(item, region=region, now=now)
                if product:
                    products.append(product)
            log.info("ЦМР: вкладов и счетов %s", len(products))
        except Exception as exc:                    # noqa: BLE001
            failures.append(f"вклады: {exc}")
            log.warning("ЦМР: вклады не прочитались — %s", exc)

        for section, prefix, parse in ((LOANS, "/person/person-loans/", credit_product),
                                       (CARDS, "/person/card/", card_product)):
            try:
                index = self._get(session, section)
                visited += 1
            except Exception as exc:                # noqa: BLE001
                failures.append(f"{section}: {exc}")
                log.warning("ЦМР: раздел %s не прочитался — %s", section, exc)
                continue
            for url in section_links(index, prefix):
                time.sleep(pause)
                try:
                    product = parse(self._get(session, url), url, region=region, now=now)
                    visited += 1
                except Exception as exc:            # noqa: BLE001
                    failures.append(f"{url}: {exc}")
                    log.warning("ЦМР: %s не прочиталась — %s", url, exc)
                    continue
                if product:
                    products.append(product)
                    log.info("ЦМР: %s — %s", product.title, product.rate_raw or "ставка не указана")

        for product in products:
            product.region_method = method
        if not products:
            return self._failed("ни одного продукта: " + "; ".join(failures[:3]))
        return self._result(products=products, pages_visited=visited,
                            region_applied=method != "not_confirmed", region_method=method,
                            partial=bool(failures))
