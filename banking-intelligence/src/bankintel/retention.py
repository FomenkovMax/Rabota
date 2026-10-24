"""Очистка старых данных. По умолчанию — только план (dry-run); удаление — явным apply.

Что НЕ удаляется никогда:
  * последние `keep_snapshots` снимков каждого продукта по каждому источнику (нужны сравнению с прошлым запуском);
  * снимки, на которые ссылаются события изменений (история изменений);
  * документы, на которые ссылаются оставшиеся снимки/доступность в ЛНР, и последний документ каждого источника;
  * документы, внесённые вручную (origin=manual_import) — их нельзя получить заново;
  * запуски сбора и события изменений (небольшие, это журнал).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import ChangeEvent, Document, FetchAttempt, ProductSnapshot, RegionAvailability

log = logging.getLogger("bankintel.retention")
MIN_KEEP = 3


@dataclass
class PrunePlan:
    snapshot_ids: list[int] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)
    fetch_attempt_ids: list[int] = field(default_factory=list)

    def summary(self) -> dict:
        return {"snapshots": len(self.snapshot_ids), "documents": len(self.document_ids), "fetch_attempts": len(self.fetch_attempt_ids)}


async def plan_prune(
    session: AsyncSession, *, keep_snapshots: int = 20, attempts_days: int = 90, documents_days: int = 180, now: datetime | None = None
) -> PrunePlan:
    if keep_snapshots < MIN_KEEP:
        raise ValueError(f"keep_snapshots не может быть меньше {MIN_KEEP}: нужны предыдущие запуски для сравнения")
    now = now or datetime.now(UTC)
    plan = PrunePlan()

    # снимки: новейшие K на пару (продукт, источник) остаются
    rows = (
        await session.execute(
            select(ProductSnapshot.id, ProductSnapshot.product_id, Document.source_id)
            .join(Document, Document.id == ProductSnapshot.document_id).order_by(ProductSnapshot.id.desc())
        )
    ).all()
    seen: dict[tuple[int, int], int] = {}
    old_snaps = []
    for sid, pid, src in rows:
        seen[(pid, src)] = seen.get((pid, src), 0) + 1
        if seen[(pid, src)] > keep_snapshots:
            old_snaps.append(sid)
    protected = set((await session.scalars(select(ChangeEvent.snapshot_id).where(ChangeEvent.snapshot_id.is_not(None)))).all())
    plan.snapshot_ids = [s for s in old_snaps if s not in protected]

    # попытки загрузки
    cutoff = now - timedelta(days=attempts_days)
    plan.fetch_attempt_ids = list((await session.scalars(select(FetchAttempt.id).where(FetchAttempt.attempted_at < cutoff))).all())

    # документы
    doomed = set(plan.snapshot_ids)
    still_used = {
        d for d in (await session.scalars(select(ProductSnapshot.document_id).where(ProductSnapshot.id.not_in(doomed) if doomed else True))).all()
    } | set((await session.scalars(select(RegionAvailability.document_id).where(RegionAvailability.document_id.is_not(None)))).all())
    latest_per_source = {
        r[0] for r in (await session.execute(
            select(func.max(Document.id)).group_by(Document.source_id)
        )).all()
    }
    doc_cutoff = now - timedelta(days=documents_days)
    docs = (await session.execute(select(Document.id, Document.fetched_at, Document.origin))).all()
    for did, fetched, origin in docs:
        fetched = fetched if fetched.tzinfo else fetched.replace(tzinfo=UTC)
        if origin == "fetched" and did not in still_used and did not in latest_per_source and fetched < doc_cutoff:
            plan.document_ids.append(did)
    return plan


async def apply_prune(session: AsyncSession, plan: PrunePlan, raw_root: Path) -> dict:
    """Удаляет по плану. Файлы удаляются только внутри raw_root и только если на них не осталось ссылок."""
    paths = []
    if plan.document_ids:
        paths = [r[0] for r in (await session.execute(select(Document.storage_path).where(Document.id.in_(plan.document_ids)))).all()]
    if plan.snapshot_ids:
        await session.execute(delete(ProductSnapshot).where(ProductSnapshot.id.in_(plan.snapshot_ids)))
    if plan.fetch_attempt_ids:
        await session.execute(delete(FetchAttempt).where(FetchAttempt.id.in_(plan.fetch_attempt_ids)))
    if plan.document_ids:
        await session.execute(delete(Document).where(Document.id.in_(plan.document_ids)))
    await session.commit()

    removed_files = 0
    root = raw_root.resolve()  # noqa: ASYNC240 — одноразовая операция обслуживания, не горячий путь
    for rel in set(paths):
        if await session.scalar(select(func.count(Document.id)).where(Document.storage_path == rel)):
            continue  # тот же файл (одинаковое содержимое) используется другим документом
        target = (root / rel).resolve()
        if root not in target.parents:  # защита от «../» в записи БД
            log.warning("пропуск файла вне хранилища: %s", rel)
            continue
        if target.is_file():
            target.unlink()
            removed_files += 1
    return {**plan.summary(), "files": removed_files}
