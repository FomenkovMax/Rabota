"""Тесты используют фрагмент реальной страницы продукта ПСБ (24.10.2026) и синтетические заглушки."""

from pathlib import Path

import pytest
from sqlalchemy import select

from bankintel.db.models import Bank, Document, FetchAttempt, Product, ProductSnapshot, Source
from bankintel.details import collect_details
from bankintel.domain.enums import FetchOutcome
from bankintel.sources import get_adapter
from bankintel.sources.base import ConditionRow, FetchDiagnostic, FetchedDocument, SourceRef
from bankintel.sources.common import ParseError, index_conditions

FIX = Path(__file__).parent / "fixtures" / "psb_detail_table.html"
REF = SourceRef("detail:1", "https://www.psbank.ru/personal/saving/myincome", "deposit")


def test_psb_detail_rows_verbatim():
    rows = get_adapter("psb")("psb").parse_detail(REF, FetchedDocument(REF.url, FIX.read_bytes()))
    d = {r.label: r.value for r in rows}
    assert d["Срок действия"] == "91 – 731 дней"
    assert d["Досрочное расторжение"].startswith("Льготное, если вклад закрывается после 90 дней")
    assert d["Пополнение"].startswith("В течение 30 дней после открытия\n")  # два абзаца -> две строки


def test_index_conditions_maps_labels_without_interpretation():
    idx = index_conditions([ConditionRow("Срок действия", "91 – 731 дней"), ConditionRow("Пополнение", "Не предусмотрено"),
                            ConditionRow("Странная подпись", "x")])
    assert idx == {"term": "91 – 731 дней", "topup": "Не предусмотрено"}


def test_psb_detail_without_table_is_error_and_vtb_detail_is_empty():
    with pytest.raises(ParseError):
        get_adapter("psb")("psb").parse_detail(REF, FetchedDocument(REF.url, b"<html>new</html>"))
    with pytest.raises(ParseError):  # у ВТБ тоже: пустая страница — это смена вёрстки, а не «нет условий»
        get_adapter("vtb")("vtb").parse_detail(REF, FetchedDocument(REF.url, b"<html/>"))


class DetailFetcher:
    def __init__(self, fail=()):
        self.fail, self.urls = set(fail), []

    async def fetch(self, source):
        self.urls.append(source.url)
        if source.url in self.fail:
            return None, FetchDiagnostic(source.key, source.url, FetchOutcome.BLOCKED, 200, "waf", 1)
        return FetchedDocument(source.url, FIX.read_bytes(), "text/html"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


async def _seed_products(s, bank_slug, urls):
    bank = await s.scalar(select(Bank).where(Bank.slug == bank_slug))
    for i, url in enumerate(urls):
        p = Product(bank_id=bank.id, category="deposit", name=f"P{i}")
        s.add(p)
        await s.flush()
        doc = Document(source_id=(await s.scalar(select(Source).where(Source.bank_id == bank.id))).id, url="u", sha256="x",
                       storage_path="x", size_bytes=1)
        s.add(doc)
        await s.flush()
        s.add(ProductSnapshot(product_id=p.id, document_id=doc.id, params={"kind": "card", "product_url": url}, extractor="rules"))
    await s.commit()
    return bank


async def test_collect_details_ok(seeded, tmp_path):
    async with seeded() as s:
        bank = await _seed_products(s, "psb", ["https://www.psbank.ru/a", "https://www.psbank.ru/b"])
        run = await collect_details(s, bank, DetailFetcher(), tmp_path)
        assert run.status == "ok"
        snaps = (await s.scalars(select(ProductSnapshot).where(ProductSnapshot.extractor == "rules"))).all()
        cond = [x for x in snaps if x.params["kind"] == "conditions"]
        assert len(cond) == 2 and cond[0].params["conditions"]["term"] == "91 – 731 дней"
        assert cond[0].params["conditions_raw"][0]["label"] == "Валюта"
        # производные источники и документы с трассировкой
        assert {x.key for x in (await s.scalars(select(Source).where(Source.key.like("detail:%")))).all()} == {
            f"detail:{p.id}" for p in (await s.scalars(select(Product))).all()}
        # повторный запуск не плодит источники
        await collect_details(s, bank, DetailFetcher(), tmp_path)
        assert len((await s.scalars(select(Source).where(Source.key.like("detail:%")))).all()) == 2


async def test_collect_details_partial_and_foreign_link(seeded, tmp_path):
    async with seeded() as s:
        bank = await _seed_products(s, "psb", ["https://www.psbank.ru/a", "https://www.psbank.ru/b", "https://evil.example.com/c"])
        f = DetailFetcher(fail={"https://www.psbank.ru/b"})
        run = await collect_details(s, bank, f, tmp_path)
        assert run.status == "partial"
        assert "https://evil.example.com/c" not in f.urls  # чужой домен не запрашивается
        assert "blocked" in run.message and "вне официальных доменов" in run.message
        attempts = (await s.scalars(select(FetchAttempt))).all()
        assert {a.outcome for a in attempts} == {"ok", "blocked"}


VTB_FIX = Path(__file__).parent / "fixtures" / "vtb_detail_faq.html"


class VtbDetailFetcher(DetailFetcher):
    def __init__(self, content):
        super().__init__()
        self.content = content

    async def fetch(self, source):
        return FetchedDocument(source.url, self.content, "text/html"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


async def test_vtb_details_faq_rows_stored_without_invented_fields(seeded, tmp_path):
    async with seeded() as s:
        bank = await _seed_products(s, "vtb", ["https://www.vtb.ru/personal/vklady-i-scheta/x/"])
        run = await collect_details(s, bank, VtbDetailFetcher(VTB_FIX.read_bytes()), tmp_path)
        assert run.status == "ok" and not run.message  # прежняя пометка «нужен этап 3» больше не нужна
        (cond,) = [x for x in (await s.scalars(select(ProductSnapshot))).all() if x.params["kind"] == "conditions"]
        assert cond.extractor == "rules"
        assert cond.params["conditions"] == {}  # в поля (срок, сумма, пополнение…) не разбираем — это этап 3
        raw = cond.params["conditions_raw"]
        assert len(raw) == 5 and all(r["label"].startswith("Вопрос: ") for r in raw)


async def test_vtb_details_layout_change_is_failure_not_empty_success(seeded, tmp_path):
    async with seeded() as s:
        bank = await _seed_products(s, "vtb", ["https://www.vtb.ru/personal/vklady-i-scheta/x/"])
        run = await collect_details(s, bank, VtbDetailFetcher(b"<html><body>new layout</body></html>"), tmp_path)
        # страница загружена и сохранена, но не разобрана: не «ok» и не пустой успех
        assert run.status == "partial" and "parse_error" in run.message and "вёрстка изменилась" in run.message
        assert "conditions" not in [x.params["kind"] for x in (await s.scalars(select(ProductSnapshot))).all()]
