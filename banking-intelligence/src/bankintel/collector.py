"""Запуск сбора по банку: адаптер -> сохранение документов, диагностики, продуктов."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import (
    Bank,
    CollectionRun,
    Document,
    FetchAttempt,
    Product,
    ProductSnapshot,
    RegionAvailability,
    Source,
)
from bankintel.domain.enums import CollectionStatus, SourceStatus
from bankintel.sources import get_adapter
from bankintel.sources.base import Fetcher, SourceRef
from bankintel.sources.storage import save_raw


async def collect_bank(
    session: AsyncSession,
    bank: Bank,
    fetcher: Fetcher,
    raw_root: Path,
    *,
    include_todo: bool = False,
) -> CollectionRun:
    """include_todo=True нужен только для зондирования корня сайта (probe); обычный сбор
    идёт по источникам, URL которых подтверждён человеком (status=active)."""
    wanted = {SourceStatus.ACTIVE.value} | ({SourceStatus.TODO.value} if include_todo else set())
    rows = (
        await session.scalars(select(Source).where(Source.bank_id == bank.id, Source.status.in_(wanted)))
    ).all()
    by_key = {r.key: r for r in rows}
    refs = [SourceRef(r.key, r.url, r.category) for r in rows]

    run = CollectionRun(bank_id=bank.id, status="running")
    session.add(run)
    await session.flush()

    result = await get_adapter(bank.adapter)(bank.slug, fetcher).collect(refs)

    for d in result.diagnostics:
        session.add(
            FetchAttempt(
                source_id=by_key[d.source_key].id, outcome=d.outcome.value,
                http_status=d.http_status, error=d.error, duration_ms=d.duration_ms,
            )
        )

    saved: dict[tuple[str, str], Document] = {}
    for ref, doc in result.documents:
        digest, rel = save_raw(raw_root, bank.slug, doc.content, doc.content_type)
        row = Document(
            source_id=by_key[ref.key].id, url=doc.url, fetched_at=doc.fetched_at,
            content_type=doc.content_type, sha256=digest, storage_path=rel, size_bytes=len(doc.content),
        )
        session.add(row)
        saved[(ref.key, doc.url)] = row
    await session.flush()

    for ref, doc, ep in result.products:
        document = saved[(ref.key, doc.url)]
        product = await session.scalar(
            select(Product).where(Product.bank_id == bank.id, Product.category == ep.category.value, Product.name == ep.name)
        )
        if product is None:
            product = Product(bank_id=bank.id, category=ep.category.value, name=ep.name)
            session.add(product)
            await session.flush()
        session.add(
            ProductSnapshot(
                product_id=product.id, document_id=document.id, params=ep.params,
                evidence=ep.evidence, extractor="rules",
            )
        )
        avail = await session.scalar(select(RegionAvailability).where(RegionAvailability.product_id == product.id))
        if avail is None:
            avail = RegionAvailability(product_id=product.id)
            session.add(avail)
        avail.status, avail.quote, avail.document_id = ep.lnr_status.value, ep.lnr_quote, document.id
        avail.checked_at = datetime.now(UTC)

    run.status = result.status.value
    run.message = "; ".join(result.messages)[:2000] or None
    run.finished_at = datetime.now(UTC)
    await session.commit()
    return run


async def collect_all(session: AsyncSession, fetcher: Fetcher, raw_root: Path, **kw) -> list[tuple[Bank, CollectionRun]]:
    banks = (await session.scalars(select(Bank).order_by(Bank.id))).all()
    return [(b, await collect_bank(session, b, fetcher, raw_root, **kw)) for b in banks]


__all__ = ["collect_bank", "collect_all", "CollectionStatus"]
