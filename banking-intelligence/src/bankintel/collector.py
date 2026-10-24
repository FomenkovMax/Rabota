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
from bankintel.monitor import detect_changes
from bankintel.sources import get_adapter
from bankintel.sources.base import Fetcher, SourceRef
from bankintel.sources.manual import ManualFetcher
from bankintel.sources.storage import save_raw


async def collect_bank(
    session: AsyncSession,
    bank: Bank,
    fetcher: Fetcher,
    raw_root: Path,
    *,
    include_todo: bool = False,
    mode: str = "fetch",
) -> CollectionRun:
    """include_todo=True нужен только для зондирования корня сайта (probe); обычный сбор
    идёт по источникам, URL которых подтверждён человеком (status=active)."""
    wanted = {SourceStatus.ACTIVE.value} | ({SourceStatus.TODO.value} if include_todo else set())
    rows = (
        await session.scalars(
            select(Source).where(Source.bank_id == bank.id, Source.status.in_(wanted), Source.mode == mode)
        )
    ).all()
    if mode == "manual":
        fetcher = ManualFetcher(session, raw_root)
    by_key = {r.key: r for r in rows}
    refs = [SourceRef(r.key, r.url, r.category) for r in rows]

    run = CollectionRun(bank_id=bank.id, status="running")
    session.add(run)
    await session.flush()

    result = await get_adapter(bank.adapter)(bank.slug, fetcher).collect(refs)

    for d in result.diagnostics if mode == "fetch" else []:
        session.add(
            FetchAttempt(
                source_id=by_key[d.source_key].id, run_id=run.id, outcome=d.outcome.value,
                http_status=d.http_status, error=d.error, duration_ms=d.duration_ms,
            )
        )

    saved: dict[tuple[str, str], Document] = {}
    for ref, doc in result.documents:
        if doc.document_id is not None:  # уже в БД (ручной импорт) — не дублируем
            saved[(ref.key, doc.url)] = await session.get(Document, doc.document_id)
            continue
        digest, rel = save_raw(raw_root, bank.slug, doc.content, doc.content_type)
        row = Document(
            source_id=by_key[ref.key].id, url=doc.url, fetched_at=doc.fetched_at,
            content_type=doc.content_type, sha256=digest, storage_path=rel, size_bytes=len(doc.content), run_id=run.id,
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
                evidence=ep.evidence, extractor="rules", run_id=run.id,
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
    await detect_changes(session, run)
    return run


async def collect_all(session: AsyncSession, fetcher: Fetcher, raw_root: Path, **kw) -> list[tuple[Bank, CollectionRun]]:
    """Сбор по всем банкам. Банки с manual-источниками дополнительно обрабатываются по ранее
    импортированным документам (без обращения к сети)."""
    banks = (await session.scalars(select(Bank).order_by(Bank.id))).all()
    out = []
    for b in banks:
        out.append((b, await collect_bank(session, b, fetcher, raw_root, **kw)))
        has_manual = await session.scalar(select(Source.id).where(Source.bank_id == b.id, Source.mode == "manual").limit(1))
        if has_manual:
            out.append((b, await collect_bank(session, b, fetcher, raw_root, mode="manual")))
    return out


__all__ = ["collect_bank", "collect_all", "CollectionStatus"]
