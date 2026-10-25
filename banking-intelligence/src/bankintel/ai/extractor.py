"""Конвейер AI-извлечения условий со страниц продуктов.

Защита данных: во внешний API уходит только текст ПУБЛИЧНОЙ страницы с официального домена банка (проверяется);
внутренние данные банка сюда попасть не могут — источник текста один (сохранённые документы).
Расход: лимит документов за запуск, кэш по хешу документа и версии подсказки, режим dry-run без вызовов."""

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.ai.client import LLMClient
from bankintel.ai.schemas import PROMPT_VERSION, SYSTEM_PROMPT, AiConditions
from bankintel.ai.text import html_to_text
from bankintel.ai.verify import lnr_status, verify
from bankintel.db.models import Bank, Document, Product, ProductSnapshot, RegionAvailability, Source

log = logging.getLogger("bankintel.ai")
MIN_TEXT = 500
ALLOWED_ORIGINS = ("fetched", "manual_import")


@dataclass
class ExtractionReport:
    dry_run: bool
    considered: int = 0
    skipped: list[str] = field(default_factory=list)
    to_send: int = 0
    chars: int = 0
    stored: int = 0
    failed: list[str] = field(default_factory=list)
    facts_accepted: int = 0
    facts_rejected: int = 0
    lnr_updates: int = 0


def _official(url: str, bank: Bank) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    base = (urlparse(bank.website).hostname or "").lower().removeprefix("www.")
    return host == base or host.endswith("." + base)


async def _candidates(session: AsyncSession):
    latest = select(func.max(Document.id)).join(Source, Source.id == Document.source_id).where(Source.key.like("detail:%")).group_by(Document.source_id)
    rows = (
        await session.execute(
            select(Document, Source, Bank).join(Source, Source.id == Document.source_id).join(Bank, Bank.id == Source.bank_id)
            .where(Document.id.in_(latest)).order_by(Bank.id, Document.id)
        )
    ).all()
    # Приоритет: продукты, у которых правилами условия НЕ извлечены (там AI нужнее всего); внутри группы — порядок банков.
    # «Извлечены» = есть разобранные поля; сохранённый дословный текст (FAQ ВТБ) полей не даёт и AI не заменяет.
    conditions = {
        r[0] for r in (await session.execute(select(ProductSnapshot.product_id, ProductSnapshot.params))).all()
        if r[1].get("kind") == "conditions" and r[1].get("conditions")
    }

    def has_rule_conditions(row) -> bool:
        m = re.fullmatch(r"detail:(\d+)", row[1].key)
        return bool(m) and int(m.group(1)) in conditions

    return sorted(rows, key=lambda r: (has_rule_conditions(r), r[2].id, r[0].id))


async def run_extraction(
    session: AsyncSession, settings, client: LLMClient | None, *, dry_run: bool = True, limit: int | None = None
) -> ExtractionReport:
    if not dry_run and client is None:
        raise ValueError("для реального запуска нужен клиент LLM")
    rep = ExtractionReport(dry_run=dry_run)
    budget = min(limit or settings.ai_max_docs_per_run, settings.ai_max_docs_per_run)
    schema = AiConditions.model_json_schema()
    model = getattr(client, "model", None) or settings.ai_model or "dry-run"

    for doc, source, bank in await _candidates(session):
        rep.considered += 1
        match = re.fullmatch(r"detail:(\d+)", source.key)
        product = await session.get(Product, int(match.group(1))) if match else None
        label = f"{bank.name} · {product.name if product else source.key}"
        if product is None:
            rep.skipped.append(f"{label}: продукт не найден")
            continue
        if doc.origin not in ALLOWED_ORIGINS or not _official(doc.url, bank):
            rep.skipped.append(f"{label}: документ не с официального домена банка — не отправляется")
            continue
        if not (doc.content_type or "").startswith("text/html"):
            rep.skipped.append(f"{label}: не HTML")
            continue
        cached = await session.scalar(
            select(ProductSnapshot.id).where(
                ProductSnapshot.product_id == product.id, ProductSnapshot.document_id == doc.id,
                ProductSnapshot.extractor.like("llm:%"),
            ).limit(1)
        )
        cached_ok = False
        if cached:
            snap = await session.get(ProductSnapshot, cached)
            cached_ok = snap.params.get("prompt_version") == PROMPT_VERSION and snap.params.get("document_sha256") == doc.sha256
        if cached_ok:
            rep.skipped.append(f"{label}: уже извлечено для этого документа")
            continue
        raw_root = settings.raw_storage_dir
        text, truncated = html_to_text((raw_root / doc.storage_path).read_bytes(), settings.ai_max_chars)
        if len(text) < MIN_TEXT:
            rep.skipped.append(f"{label}: слишком мало текста ({len(text)} симв.)")
            continue
        if rep.to_send >= budget:
            rep.skipped.append(f"{label}: исчерпан лимит документов за запуск ({budget})")
            continue
        rep.to_send += 1
        rep.chars += len(text)
        if dry_run:
            continue

        user = f"Продукт: {product.name} ({bank.name}).\nТекст страницы между <<< и >>>:\n<<<\n{text}\n>>>"
        log.info("AI: документ id=%s, %s симв.", doc.id, len(text))  # содержимое в лог не пишем
        try:
            raw = await client.extract(SYSTEM_PROMPT, user, schema)
        except Exception as exc:
            rep.failed.append(f"{label}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        result = verify(raw, text)
        if result.schema_error:
            rep.failed.append(f"{label}: ответ не соответствует схеме")
        rep.facts_accepted += len(result.facts)
        rep.facts_rejected += len(result.rejected)
        status, quote = lnr_status(result.lnr)
        session.add(ProductSnapshot(
            product_id=product.id, document_id=doc.id, extractor=f"llm:{model}",
            params={"kind": "ai_conditions", "page_key": "detail", "prompt_version": PROMPT_VERSION, "document_sha256": doc.sha256,
                    "truncated": truncated, "facts": result.facts, "rejected": result.rejected, "lnr_mentions": result.lnr,
                    "schema_error": result.schema_error},
            evidence={k: v["quote"] for k, v in result.facts.items()},
        ))
        if result.lnr:
            av = await session.scalar(select(RegionAvailability).where(RegionAvailability.product_id == product.id))
            if av is None:
                av = RegionAvailability(product_id=product.id)
                session.add(av)
            av.status, av.quote, av.document_id = status, quote, doc.id
            rep.lnr_updates += 1
        rep.stored += 1
        await session.commit()
    return rep
