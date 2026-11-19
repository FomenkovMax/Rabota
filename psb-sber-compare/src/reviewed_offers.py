"""Optional, dated supplements reviewed against published terms and local sources."""
from datetime import date
import json
import logging
from urllib.parse import urlsplit

from . import availability
from .promos import classify
from .psb.parser import Product

log = logging.getLogger(__name__)


def _https(value: str) -> bool:
    url = urlsplit(value)
    return url.scheme == "https" and bool(url.hostname)


def load(path, banks, today: date):
    products, statuses, promos = [], {}, []
    try:
        batch = json.loads(path.read_text(encoding="utf-8"))
        for row in batch["tariffs"]:
            if row["bank"] not in banks or not _https(row["source"]):
                continue
            product = Product(bank=row["bank"], title=row["title"], category=row["category"],
                              url_path=row["source"], source_url=row["source"],
                              collected_at=row["checked_at"], terms=dict(row["terms"]))
            if rate := row.get("rate"):
                product.rate_min = product.rate_max = rate
                product.rate_raw = f"{rate}%"
            geography = row.get("geography")
            statuses[id(product)] = availability.Status(
                availability.UNKNOWN, product.terms.get("География", "Нет подтверждения региона для тарифа"),
                product.source_url)
            if geography and _https(geography["source"]):
                reason = geography["reason"]
                if geography["scope"] == "lugansk":
                    reason = f"есть подтверждение услуги в Луганске: г. Луганск. {reason}"
                if geography["scope"] in {"lnr", "lugansk"}:
                    statuses[id(product)] = availability.Status(
                        availability.LNR, reason, geography["source"])
                    product.region_method = "selector"
            periods = row.get("scenario")
            if periods:
                product.amount_min = product.amount_max = periods["amount"]
                if "days" in periods:
                    product.term_raw = f'{periods["days"]} дней'
                    product.terms["Точный срок, дней"] = str(periods["days"])
                else:
                    product.term_min_months = product.term_max_months = periods["months"]
                    product.term_raw = f'{periods["months"]} мес.'
                    product.terms["Точный срок, месяцев"] = str(periods["months"])
                if "basis" in periods:
                    product.terms["База начисления процентов"] = periods["basis"]
            if bounds := row.get("published_psk"):
                product.apr_min, product.apr_max = bounds
                product.apr_raw = f'{product.apr_min:.3f}–{product.apr_max:.3f}%'.replace(".", ",")
            products.append(product)
        for row in batch["promotions"]:
            if row["bank"] not in banks or not _https(row["rules"]) or not _https(row["regional_source"]):
                continue
            promo = classify(row["bank"], row["title"], row["text"], row["rules"], "",
                             today=today)
            if promo is not None:
                promo.source_url = row["rules"]
                promo.checked_at = row["checked_at"]
                promo.regional_source = row["regional_source"]
                promos.append(promo)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        log.warning("Сверка условий %s не загружена: %s", path, exc)
        return [], {}, []
    return products, statuses, promos
