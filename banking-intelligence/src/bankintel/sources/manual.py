"""Ручной импорт: документы, которые человек сохранил из браузера (сайт недоступен загрузчику).

Мы не обходим защиту сайтов. Импортированный документ хранится с пометкой origin=manual_import;
дата `fetched_at` — это дата сохранения, указанная человеком.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, Document, Source
from bankintel.domain.enums import FetchOutcome
from bankintel.sources.base import FetchDiagnostic, FetchedDocument, SourceRef
from bankintel.sources.fetcher import looks_blocked
from bankintel.sources.storage import save_raw

CONTENT_TYPES = {".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf"}


class ManualImportError(Exception):
    pass


def _host_ok(url: str, hosts: set[str]) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in hosts)


async def import_document(
    session: AsyncSession,
    bank: Bank,
    *,
    source_key: str,
    url: str,
    category: str,
    file_path: Path,
    captured_at: datetime,
    official_hosts: set[str],
    raw_root: Path,
    note: str | None = None,
) -> Document:
    if not _host_ok(url, official_hosts):
        raise ManualImportError(f"URL {url} не входит в официальные домены банка {sorted(official_hosts)}")
    if captured_at.tzinfo is None:
        raise ManualImportError("captured_at должен содержать часовой пояс (например 2026-10-24T12:00+03:00)")
    content_type = CONTENT_TYPES.get(file_path.suffix.lower())
    if content_type is None:
        raise ManualImportError(f"Поддерживаются {sorted(CONTENT_TYPES)}, получен {file_path.suffix!r}")
    content = await asyncio.to_thread(file_path.read_bytes)
    if not content:
        raise ManualImportError("Файл пустой")
    if content_type == "text/html" and looks_blocked(200, content):
        raise ManualImportError("Файл похож на страницу блокировки/капчи, а не на страницу банка")

    source = await session.scalar(select(Source).where(Source.bank_id == bank.id, Source.key == source_key))
    if source is None:
        source = Source(bank_id=bank.id, key=source_key, url=url, category=category, status="active", mode="manual")
        session.add(source)
        await session.flush()
    elif source.mode != "manual":
        raise ManualImportError(f"Источник {source_key} настроен на автоматическую загрузку (mode={source.mode})")

    digest, rel = save_raw(raw_root, bank.slug, content, content_type)
    doc = Document(
        source_id=source.id, url=url, fetched_at=captured_at, content_type=content_type, sha256=digest,
        storage_path=rel, size_bytes=len(content), origin="manual_import", note=note,
    )
    session.add(doc)
    await session.commit()
    return doc


class ManualFetcher:
    """Отдаёт последний импортированный документ источника из БД и файлового хранилища."""

    def __init__(self, session: AsyncSession, raw_root: Path):
        self.session, self.raw_root = session, raw_root

    async def fetch(self, source: SourceRef) -> tuple[FetchedDocument | None, FetchDiagnostic]:
        row = await self.session.execute(
            select(Document).join(Source, Source.id == Document.source_id)
            .where(Source.key == source.key, Source.url == source.url, Document.origin == "manual_import")
            .order_by(Document.fetched_at.desc(), Document.id.desc()).limit(1)
        )
        doc = row.scalar_one_or_none()
        if doc is None:
            return None, FetchDiagnostic(source.key, source.url, FetchOutcome.HTTP_ERROR, None, "документ не импортирован")
        content = (self.raw_root / doc.storage_path).read_bytes()
        return (
            FetchedDocument(doc.url, content, doc.content_type, 200, doc.fetched_at, document_id=doc.id),
            FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200),
        )
