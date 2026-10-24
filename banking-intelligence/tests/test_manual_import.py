"""Данные синтетические (тестовые)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from bankintel.collector import collect_bank
from bankintel.db.models import Bank, Document, FetchAttempt, Product, ProductSnapshot, Source
from bankintel.sources.manual import ManualImportError, import_document

HOSTS = {"sberbank.ru"}
WHEN = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
URL = "https://www.sberbank.ru/ru/person/synthetic"


async def _import(s, bank, tmp_path, content=b"<html>synthetic page</html>", name="p.html", **kw):
    f = tmp_path / name
    f.write_bytes(content)
    args = dict(source_key="deposits", url=URL, category="deposit", file_path=f, captured_at=WHEN,
                official_hosts=HOSTS, raw_root=tmp_path / "raw")
    args.update(kw)
    return await import_document(s, bank, **args)


async def _sber(s):
    return await s.scalar(select(Bank).where(Bank.slug == "sber"))


async def test_import_stores_with_manual_origin(seeded, tmp_path):
    async with seeded() as s:
        doc = await _import(s, await _sber(s), tmp_path, note="сохранено из Chrome")
        assert doc.origin == "manual_import" and doc.fetched_at.replace(tzinfo=UTC) == WHEN
        assert (tmp_path / "raw" / doc.storage_path).read_bytes() == b"<html>synthetic page</html>"
        src = await s.scalar(select(Source).where(Source.id == doc.source_id))
        assert src.mode == "manual" and src.status == "active"


@pytest.mark.parametrize(
    "kw,content,msg",
    [
        ({"url": "https://evil.example.com/x"}, b"<html>x</html>", "официальные домены"),
        ({"captured_at": datetime(2026, 1, 1)}, b"<html>x</html>", "часовой пояс"),
        ({"name": "p.txt"}, b"x", "Поддерживаются"),
        ({}, b"", "пустой"),
        ({}, "<html>{code:'user_blocked'} Возникла проблема при открытии сайта</html>".encode(), "блокировки"),
    ],
)
async def test_import_rejects_bad_input(seeded, tmp_path, kw, content, msg):
    async with seeded() as s:
        with pytest.raises(ManualImportError, match=msg):
            await _import(s, await _sber(s), tmp_path, content=content, **kw)


async def test_import_refuses_fetch_mode_source(seeded, tmp_path):
    async with seeded() as s:
        psb = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        with pytest.raises(ManualImportError, match="автоматическую загрузку"):
            await _import(s, psb, tmp_path, source_key="deposits", url="https://www.psbank.ru/personal/saving",
                          official_hosts={"psbank.ru"})


async def test_manual_collection_parses_without_network_or_duplicates(seeded, tmp_path):
    from test_collector import SyntheticAdapter  # noqa: F401  (регистрирует "synthetic")

    class Boom:  # сеть для manual-сбора не нужна
        async def fetch(self, source):
            raise AssertionError("сеть не должна использоваться")

    async with seeded() as s:
        bank = await _sber(s)
        bank.adapter = "synthetic"
        await _import(s, bank, tmp_path)
        run = await collect_bank(s, bank, Boom(), tmp_path / "raw", mode="manual")
        assert run.status == "ok"
        assert len((await s.scalars(select(Document))).all()) == 1  # документ не продублирован
        assert (await s.scalars(select(FetchAttempt))).all() == []
        snap = await s.scalar(select(ProductSnapshot))
        doc = await s.scalar(select(Document))
        assert snap.document_id == doc.id and doc.origin == "manual_import"
        assert len((await s.scalars(select(Product))).all()) == 1


async def test_manual_collection_without_document_is_reported(seeded, tmp_path):
    async with seeded() as s:
        bank = await _sber(s)
        s.add(Source(bank_id=bank.id, key="m", url=URL, category="deposit", status="active", mode="manual"))
        await s.commit()
        run = await collect_bank(s, bank, object(), tmp_path, mode="manual")
        assert run.status == "failed" and "не импортирован" in run.message


async def test_fetch_collection_ignores_manual_sources(seeded, tmp_path):
    class F:
        async def fetch(self, source):
            raise AssertionError("manual-источник не должен загружаться")

    async with seeded() as s:
        bank = await _sber(s)
        s.add(Source(bank_id=bank.id, key="m", url=URL, category="deposit", status="active", mode="manual"))
        await s.commit()
        run = await collect_bank(s, bank, F(), tmp_path)
        assert run.status == "failed" and "Нет активных" in run.message
