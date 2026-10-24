"""Все данные здесь СИНТЕТИЧЕСКИЕ (тестовые) и нигде, кроме тестов, не используются."""

from sqlalchemy import select

from bankintel.bot import handlers, views
from bankintel.collector import collect_all, collect_bank
from bankintel.db.models import Bank, Document, FetchAttempt, Product, ProductSnapshot, RegionAvailability, Source
from bankintel.domain.enums import AvailabilityStatus, FetchOutcome, ProductCategory
from bankintel.sources.base import BankAdapter, ExtractedProduct, FetchDiagnostic, FetchedDocument, register_adapter


@register_adapter("synthetic")
class SyntheticAdapter(BankAdapter):
    def parse(self, source, doc):
        return [
            ExtractedProduct(
                "SYNTHETIC-PRODUCT", ProductCategory.DEPOSIT, {"rate_text": "SYNTH"},
                {"rate_text": "SYNTH"}, AvailabilityStatus.NOT_CONFIRMED,
            )
        ]


class FakeFetcher:
    def __init__(self, ok=True):
        self.ok = ok

    async def fetch(self, source):
        if not self.ok:
            return None, FetchDiagnostic(source.key, source.url, FetchOutcome.TLS_ERROR, None, "cert", 5)
        return FetchedDocument(source.url, b"<html>synthetic</html>", "text/html"), FetchDiagnostic(
            source.key, source.url, FetchOutcome.OK, 200, None, 5
        )


async def _bank(seeded, slug="sber", adapter="synthetic", status="active"):
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == slug))
        bank.adapter = adapter
        for src in (await s.scalars(select(Source).where(Source.bank_id == bank.id))).all():
            src.status = status
        await s.commit()


async def test_todo_sources_not_collected_by_default(seeded, tmp_path):
    async with seeded() as s:
        run = await collect_bank(s, await s.scalar(select(Bank).where(Bank.slug == "sber")), FakeFetcher(), tmp_path)
        assert run.status == "failed" and "Нет активных" in run.message
        assert (await s.scalars(select(FetchAttempt))).all() == []


async def test_probe_includes_todo(seeded, tmp_path):
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        run = await collect_bank(s, bank, FakeFetcher(), tmp_path, include_todo=True)
        assert run.status == "ok"
        assert len((await s.scalars(select(Document))).all()) == 1


async def test_success_persists_provenance(seeded, tmp_path):
    await _bank(seeded)
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        run = await collect_bank(s, bank, FakeFetcher(), tmp_path)
        assert run.status == "ok"
        doc = await s.scalar(select(Document))
        assert (tmp_path / doc.storage_path).read_bytes() == b"<html>synthetic</html>"
        snap = await s.scalar(select(ProductSnapshot))
        assert snap.document_id == doc.id and snap.evidence == {"rate_text": "SYNTH"}
        av = await s.scalar(select(RegionAvailability))
        assert av.status == "not_confirmed" and av.quote is None
        # повторный сбор не дублирует продукт, но добавляет снимок
        await collect_bank(s, bank, FakeFetcher(), tmp_path)
        assert len((await s.scalars(select(Product))).all()) == 1
        assert len((await s.scalars(select(ProductSnapshot))).all()) == 2


async def test_failure_keeps_diagnostics(seeded, tmp_path):
    await _bank(seeded)
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        run = await collect_bank(s, bank, FakeFetcher(ok=False), tmp_path)
        assert run.status == "failed" and "tls_error" in run.message
        att = await s.scalar(select(FetchAttempt))
        assert att.outcome == "tls_error" and att.error == "cert"
        assert (await s.scalars(select(Product))).all() == []
        text = await views.status_text(s)
        assert "tls_error" in text


class _Closable(FakeFetcher):
    async def aclose(self):
        pass


async def _run_refresh(seeded, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from bankintel.config import get_settings

    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(handlers, "build_fetcher", lambda settings: _Closable())
    get_settings.cache_clear()
    m = AsyncMock()
    await handlers.cmd_refresh(m, session_factory=seeded)
    get_settings.cache_clear()
    return m.answer.call_args.args[0]


async def test_refresh_handler_reports_no_active_sources(seeded, tmp_path, monkeypatch):
    async with seeded() as s:
        for src in (await s.scalars(select(Source))).all():
            src.status = "todo"
        await s.commit()
    assert "Активных источников нет" in await _run_refresh(seeded, tmp_path, monkeypatch)


async def test_refresh_handler_collects_active_sources(seeded, tmp_path, monkeypatch):
    text = await _run_refresh(seeded, tmp_path, monkeypatch)  # в конфиге активны ПСБ и ВТБ
    assert "Активных источников нет" not in text
    assert "ПСБ: <b>ok</b>" in text and "ВТБ: <b>ok</b>" in text
