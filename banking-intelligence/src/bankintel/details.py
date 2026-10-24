"""Сбор страниц отдельных продуктов и извлечение условий.

Ссылки берутся из `product_url` карточек на подтверждённых страницах (только официальные
домены банка). Для каждого продукта создаётся производный источник `detail:<product_id>`.
Условия сохраняются как отдельный снимок (params.kind = "conditions") с дословными значениями.
"""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, CollectionRun, Document, FetchAttempt, Product, ProductSnapshot, Source
from bankintel.domain.enums import CollectionStatus
from bankintel.sources import get_adapter
from bankintel.sources.base import Fetcher, SourceRef
from bankintel.sources.common import index_conditions
from bankintel.sources.storage import save_raw


def _official(url: str, bank: Bank) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    base = (urlparse(bank.website).hostname or "").lower().removeprefix("www.")
    return host == base or host.endswith("." + base)


async def collect_details(session: AsyncSession, bank: Bank, fetcher: Fetcher, raw_root: Path) -> CollectionRun:
    run = CollectionRun(bank_id=bank.id, status="running")
    session.add(run)
    await session.flush()
    adapter = get_adapter(bank.adapter)(bank.slug, fetcher)
    messages: list[str] = []
    fetched = failed = empty = 0

    products = (await session.scalars(select(Product).where(Product.bank_id == bank.id, Product.is_active))).all()
    for product in products:
        snaps = (
            await session.scalars(
                select(ProductSnapshot).where(ProductSnapshot.product_id == product.id).order_by(ProductSnapshot.id.desc())
            )
        ).all()
        url = next((s.params.get("product_url") for s in snaps if s.params.get("product_url")), None)
        if not url:
            continue
        if not _official(url, bank):
            messages.append(f"{product.name}: ссылка {url} вне официальных доменов банка — пропущена")
            failed += 1
            continue
        key = f"detail:{product.id}"
        source = await session.scalar(select(Source).where(Source.bank_id == bank.id, Source.key == key))
        if source is None:
            source = Source(
                bank_id=bank.id, key=key, url=url, category=product.category, status="active", mode="fetch",
                notes="Производный источник: ссылка карточки на подтверждённой странице списка продуктов.",
            )
            session.add(source)
            await session.flush()
        ref = SourceRef(key, url, product.category)

        doc, diag = await fetcher.fetch(ref)
        session.add(
            FetchAttempt(source_id=source.id, outcome=diag.outcome.value, http_status=diag.http_status,
                         error=diag.error, duration_ms=diag.duration_ms)
        )
        if doc is None:
            failed += 1
            messages.append(f"{product.name}: {diag.outcome.value} {diag.error or ''}".strip())
            continue
        digest, rel = save_raw(raw_root, bank.slug, doc.content, doc.content_type)
        row = Document(source_id=source.id, url=doc.url, fetched_at=doc.fetched_at, content_type=doc.content_type,
                       sha256=digest, storage_path=rel, size_bytes=len(doc.content))
        session.add(row)
        await session.flush()
        fetched += 1
        try:
            conditions = adapter.parse_detail(ref, doc)
        except Exception as exc:
            failed += 1
            messages.append(f"{product.name}: parse_error {type(exc).__name__}: {exc}"[:300])
            continue
        if not conditions:
            empty += 1
            continue
        session.add(
            ProductSnapshot(
                product_id=product.id, document_id=row.id, extractor="rules",
                params={
                    "kind": "conditions", "page_key": "detail", "product_url": url,
                    "conditions": index_conditions(conditions),
                    "conditions_raw": [{"label": c.label, "value": c.value} for c in conditions],
                },
                evidence={c.label: c.value for c in reversed(conditions)},
            )
        )

    if empty:
        messages.append(f"условия не извлечены правилами для {empty} стр. (документы сохранены; нужен этап 3)")
    total = fetched + failed
    if total == 0:
        status, messages = CollectionStatus.FAILED, ["Нет продуктов со ссылками на страницы"]
    elif failed == total:
        status = CollectionStatus.FAILED
    elif failed or empty:
        status = CollectionStatus.PARTIAL
    else:
        status = CollectionStatus.OK
    run.status, run.message, run.finished_at = status.value, "; ".join(messages)[:2000] or None, datetime.now(UTC)
    await session.commit()
    return run
