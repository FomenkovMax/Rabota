"""ПСБ: SSR-состояние Angular прямо в HTML.

Единственный из пяти банков, чьи данные берутся обычным HTTP-запросом.
Подробности разбора — в src/psb/.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..psb.catalog import RETAIL_SECTIONS, build_catalog
from ..psb.client import PageNotFound, PsbClient, REGIONS
from ..psb.parser import parse_product
from .base import BankAdapter, CollectResult, registry

log = logging.getLogger(__name__)


@registry.register
class PsbAdapter(BankAdapter):
    code = "psb"
    title = "ПСБ"
    strategy = "SSR-состояние страницы, обычный HTTP-запрос"
    verified = True

    def collect(self) -> CollectResult:
        settings = self.settings
        region_key = settings.get("region", "lugansk")
        region = REGIONS.get(region_key)
        if region is None:
            return self._failed(f"Неизвестный регион «{region_key}»")

        region_label = settings.get("region_label", region.city_name)
        sections = settings.get("sections") or []
        include_promos = bool(settings.get("include_promos", True))
        max_pages = int(settings.get("max_pages", 0) or 0)
        now = datetime.now().isoformat(timespec="seconds")

        client = PsbClient(
            region=region,
            pause=float(settings.get("pause", 1.5)),
            timeout=int(settings.get("timeout", 30)),
            retries=int(settings.get("retries", 3)),
            throttle_backoff=int(settings.get("throttle_backoff", 30)),
        )

        products, promos = [], []
        missing = failed = visited = 0

        try:
            with client:
                pages = build_catalog(client.get("/personal/loans"),
                                      include_promos=include_promos)
                if sections:
                    unknown = [s for s in sections if s not in RETAIL_SECTIONS]
                    if unknown:
                        log.warning("Неизвестные разделы: %s", ", ".join(unknown))
                    pages = [p for p in pages
                             if p.section in sections or p.is_promo]
                if max_pages:
                    pages = pages[:max_pages]

                log.info("ПСБ: к обходу %s страниц", len(pages))

                for index, page in enumerate(pages, 1):
                    try:
                        html_text = client.get(page.url_path)
                    except PageNotFound:
                        missing += 1
                        continue
                    except RuntimeError as exc:
                        failed += 1
                        log.warning("ПСБ пропускает %s: %s", page.url_path, exc)
                        continue

                    visited += 1
                    product = parse_product(html_text, page, region_label, now)
                    promos.extend(product.promos)
                    if product.rate_raw or product.amount_raw or len(product.terms) > 1:
                        products.append(product)

                    if index % 25 == 0:
                        log.info("  ПСБ …%s/%s", index, len(pages))
        except Exception as exc:                    # noqa: BLE001
            return self._failed(f"сбор прерван: {exc}")

        if missing:
            log.info("ПСБ: узлов без страницы %s (это нормально)", missing)
        if failed:
            log.warning("ПСБ: страниц с ошибкой %s", failed)

        unique: dict[str, object] = {}
        for promo in promos:
            unique.setdefault(promo.key(), promo)

        return self._result(products=products, promos=list(unique.values()),
                            pages_visited=visited, collected_at=now)
