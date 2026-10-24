from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_monitor import DEPOSITS, Pages, mutate

from bankintel.collector import collect_bank
from bankintel.db.models import Bank, ChangeEvent, Document, FetchAttempt, ProductSnapshot, Source
from bankintel.retention import apply_prune, plan_prune
from bankintel.sources.manual import import_document

FUTURE = datetime.now(UTC) + timedelta(days=400)  # «сейчас» далеко в будущем: всё формально устарело


async def collect_n(seeded, tmp_path, n):
    pages = Pages()
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        for i in range(n):
            pages.pages["deposits"] = mutate(DEPOSITS, "Доступен для всех", f"Доступен для всех {i}")  # каждый запуск немного иной
            await collect_bank(s, bank, pages, tmp_path)


async def count(s, model):
    return await s.scalar(select(func.count()).select_from(model))


async def test_dry_run_changes_nothing_and_keeps_last_k_per_product(seeded, tmp_path):
    await collect_n(seeded, tmp_path, 6)
    async with seeded() as s:
        before = {m: await count(s, m) for m in (ProductSnapshot, Document, FetchAttempt)}
        plan = await plan_prune(s, keep_snapshots=3, now=FUTURE)
        assert {m: await count(s, m) for m in (ProductSnapshot, Document, FetchAttempt)} == before  # план ничего не меняет
        assert plan.snapshot_ids and plan.fetch_attempt_ids

        async def pairs():
            rows = (await s.execute(
                select(ProductSnapshot.id, ProductSnapshot.product_id, Document.source_id)
                .join(Document, Document.id == ProductSnapshot.document_id).order_by(ProductSnapshot.id.desc())
            )).all()
            out = {}
            for sid, pid, src in rows:
                out.setdefault((pid, src), []).append(sid)  # от новых к старым
            return out

        original = await pairs()
        protected = set((await s.scalars(select(ChangeEvent.snapshot_id).where(ChangeEvent.snapshot_id.is_not(None)))).all())
        await apply_prune(s, plan, tmp_path)
        after = await pairs()
        for key, ids in original.items():
            assert after[key][:3] == ids[:3]                         # три новейших остались всегда
            extra = set(after[key]) - set(ids[:3])
            assert extra <= protected                                # сверх трёх — только снимки из событий изменений
        assert any(len(v) == 3 for v in after.values())              # продукты без событий урезаны ровно до трёх


async def test_last_documents_and_comparison_still_work_after_prune(seeded, tmp_path):
    await collect_n(seeded, tmp_path, 5)
    async with seeded() as s:
        await apply_prune(s, await plan_prune(s, keep_snapshots=3, now=FUTURE), tmp_path)
        # у каждого источника остался свежий документ и его файл на диске
        for src in (await s.scalars(select(Source).where(Source.mode == "fetch"))).all():
            doc = await s.scalar(select(Document).where(Document.source_id == src.id).order_by(Document.id.desc()).limit(1))
            if doc:
                assert (tmp_path / doc.storage_path).is_file()
        # мониторинг после очистки продолжает работать: следующий запуск сравнивается с оставшимся
        pages = Pages()
        pages.pages["deposits"] = mutate(DEPOSITS, "От 12,00% до 14,10%", "От 5% до 6%")
        bank = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        await collect_bank(s, bank, pages, tmp_path)
        events = (await s.scalars(select(ChangeEvent).where(ChangeEvent.change_type == "changed"))).all()
        assert any(e.diff["fields"][0]["new"] == "От 5% до 6%" for e in events)


async def test_snapshots_referenced_by_change_events_are_protected(seeded, tmp_path):
    await collect_n(seeded, tmp_path, 6)
    async with seeded() as s:
        ev_snaps = {e for e in (await s.scalars(select(ChangeEvent.snapshot_id).where(ChangeEvent.snapshot_id.is_not(None)))).all()}
        assert ev_snaps
        plan = await plan_prune(s, keep_snapshots=3, now=FUTURE)
        assert not ev_snaps & set(plan.snapshot_ids)


async def test_manual_import_documents_never_deleted(seeded, tmp_path):
    async with seeded() as s:
        sber = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        f = tmp_path / "p.html"
        f.write_bytes(b"<html>manual</html>")
        doc = await import_document(s, sber, source_key="deposits", url="https://www.sberbank.ru/x", category="deposit", file_path=f,
                                    captured_at=datetime(2020, 1, 1, tzinfo=UTC), official_hosts={"sberbank.ru"}, raw_root=tmp_path / "raw")
        # ещё один, более новый, чтобы первый не был «последним документом источника»
        f.write_bytes(b"<html>manual2</html>")
        await import_document(s, sber, source_key="deposits", url="https://www.sberbank.ru/x", category="deposit", file_path=f,
                              captured_at=datetime(2020, 2, 1, tzinfo=UTC), official_hosts={"sberbank.ru"}, raw_root=tmp_path / "raw")
        plan = await plan_prune(s, now=FUTURE)
        assert doc.id not in plan.document_ids


async def test_shared_file_and_path_traversal_are_safe(seeded, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("не трогать")
    (raw / "a.html").write_text("x")
    async with seeded() as s:
        src = await s.scalar(select(Source))
        old = datetime(2020, 1, 1, tzinfo=UTC)
        s.add_all([
            Document(source_id=src.id, url="u1", sha256="a", storage_path="a.html", size_bytes=1, fetched_at=old),
            Document(source_id=src.id, url="u2", sha256="a", storage_path="a.html", size_bytes=1, fetched_at=old),  # тот же файл
            Document(source_id=src.id, url="u3", sha256="b", storage_path="../secret.txt", size_bytes=1, fetched_at=old),  # подделанная запись
            Document(source_id=src.id, url="u4", sha256="c", storage_path="c.html", size_bytes=1, fetched_at=datetime.now(UTC)),  # последний
        ])
        await s.commit()
        plan = await plan_prune(s, now=FUTURE)
        assert len(plan.document_ids) == 3
        # удаляем только один из двух документов с общим файлом -> файл должен остаться
        first = [d for d in plan.document_ids][:1]
        plan.document_ids = first
        await apply_prune(s, plan, raw)
        assert (raw / "a.html").is_file()
        # теперь остальные: общий файл уходит, файл вне хранилища не затрагивается
        plan2 = await plan_prune(s, now=FUTURE)
        await apply_prune(s, plan2, raw)
        assert not (raw / "a.html").exists() and outside.read_text() == "не трогать"


async def test_keep_snapshots_floor():
    with pytest.raises(ValueError, match="не может быть меньше"):
        await plan_prune(None, keep_snapshots=2)


async def test_old_fetch_attempts_pruned_by_age(seeded, tmp_path):
    async with seeded() as s:
        src = await s.scalar(select(Source))
        s.add_all([FetchAttempt(source_id=src.id, outcome="ok", attempted_at=datetime.now(UTC) - timedelta(days=200)),
                   FetchAttempt(source_id=src.id, outcome="ok", attempted_at=datetime.now(UTC) - timedelta(days=5))])
        await s.commit()
        plan = await plan_prune(s)
        assert len(plan.fetch_attempt_ids) == 1
