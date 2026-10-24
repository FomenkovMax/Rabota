"""Мониторинг изменений. Страницы — фрагменты реальных страниц ПСБ; «изменения» вносятся подстановкой текста."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from bankintel.analytics.facts import load_facts
from bankintel.collector import collect_bank
from bankintel.db.models import Bank, ChangeEvent, Product
from bankintel.details import collect_details
from bankintel.domain.enums import FetchOutcome
from bankintel.monitor import detect_changes, monitoring_status, recent_changes
from bankintel.sources.base import FetchDiagnostic, FetchedDocument

FIX = Path(__file__).parent / "fixtures"
DEPOSITS = (FIX / "psb_deposits_cards.html").read_text(encoding="utf-8")
SAVINGS = (FIX / "psb_savings_cards.html").read_text(encoding="utf-8")
DETAIL = (FIX / "psb_detail_table.html").read_text(encoding="utf-8")
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def mutate(html: str, old: str, new: str) -> str:
    """Подстановка, устойчивая к неразрывным пробелам; падает, если ничего не заменила (чтобы тест не был пустым)."""
    pattern = re.escape(old).replace("\\ ", "[ \u00a0]")
    out, n = re.subn(pattern, new, html)
    assert n >= 1, f"в странице нет {old!r}"
    return out


class Pages:
    """Управляемый загрузчик: страницы по ключу источника, часть можно «сломать»."""

    def __init__(self):
        self.pages = {"deposits": DEPOSITS, "savings_accounts": SAVINGS, "savings_offers": DEPOSITS}
        self.fail: set[str] = set()
        self.detail = DETAIL

    async def fetch(self, source):
        if source.key in self.fail:
            return None, FetchDiagnostic(source.key, source.url, FetchOutcome.HTTP_ERROR, 500, "boom")
        html = self.detail if source.key.startswith("detail:") else self.pages[source.key]
        return FetchedDocument(source.url, html.encode(), "text/html"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


async def _psb(s):
    return await s.scalar(select(Bank).where(Bank.slug == "psb"))


async def run(seeded, tmp_path, pages):
    async with seeded() as s:
        await collect_bank(s, await _psb(s), pages, tmp_path)
        return (await s.scalars(select(ChangeEvent).order_by(ChangeEvent.id))).all()


async def test_first_run_is_baseline_and_identical_second_run_has_no_events(seeded, tmp_path):
    pages = Pages()
    assert await run(seeded, tmp_path, pages) == []
    assert await run(seeded, tmp_path, pages) == []
    async with seeded() as s:
        st = await monitoring_status(s)
        assert st["comparisons"] == 1 and st["since"] and st["has_data"]


async def test_rate_change_detected_with_direction_and_text(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    pages.pages["deposits"] = mutate(DEPOSITS, "От 12,00% до 14,10%", "От 11,00% до 13,50%")
    events = await run(seeded, tmp_path, pages)
    changed = [e for e in events if e.diff["source_key"] == "deposits"]
    assert len(changed) == 1 and changed[0].change_type == "changed" and changed[0].severity == "rate"
    assert changed[0].diff["direction"] == "down"
    f = changed[0].diff["fields"][0]
    assert (f["label"], f["old"], f["new"]) == ("Ставка", "От 12,00% до 14,10%", "От 11,00% до 13,50%")
    async with seeded() as s:
        (item,) = [c for c in await recent_changes(s, EPOCH) if c["diff"]["source_key"] == "deposits"]
        assert "ПСБ · Мой доход" in item["text"] and "↓" in item["text"] and "«От 11,00% до 13,50%»" in item["text"]


async def test_description_only_change_is_info(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    pages.pages["deposits"] = mutate(DEPOSITS, "Доступен для всех", "Доступен для всех клиентов банка")
    events = [e for e in await run(seeded, tmp_path, pages) if e.diff["source_key"] == "deposits"]
    assert [e.severity for e in events] == ["info"]


async def test_removed_product_deactivated_and_leaves_comparisons(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(DEPOSITS, "html.parser")
    for c in soup.select(".product-card"):
        if "Социальный вклад" in c.get_text():
            c.decompose()
    pages.pages["deposits"] = pages.pages["savings_offers"] = str(soup)
    events = await run(seeded, tmp_path, pages)
    removed = [e for e in events if e.change_type == "removed"]
    assert removed and any(e.severity == "rate" for e in removed)  # исчез с сайта целиком — значимое событие
    async with seeded() as s:
        p = await s.scalar(select(Product).where(Product.name == "Социальный вклад"))
        assert p.is_active is False
        assert "Социальный вклад" not in {f.name for f in await load_facts(s)}


async def test_failed_or_unparsable_page_does_not_remove_anything(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    pages.fail = {"deposits"}
    pages.pages["savings_offers"] = "<html>новая вёрстка</html>"  # разбор упадёт
    assert await run(seeded, tmp_path, pages) == []
    async with seeded() as s:
        assert all(p.is_active for p in (await s.scalars(select(Product))).all())


async def test_new_product_event(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(DEPOSITS, "html.parser")
    src = next(c for c in soup.select(".product-card") if "Мой доход" in c.get_text())
    clone_html = str(src)
    assert "Мой доход" in clone_html and "myincome" in clone_html
    clone = BeautifulSoup(clone_html.replace("Мой доход", "Новый вклад").replace("myincome", "newdep"), "html.parser")
    soup.body.append(clone)
    pages.pages["deposits"] = str(soup)
    events = [e for e in await run(seeded, tmp_path, pages) if e.change_type == "new" and e.diff["source_key"] == "deposits"]
    assert len(events) == 1 and events[0].severity == "rate" and events[0].diff["placement_only"] is False


async def test_placement_change_on_one_page_is_info_and_keeps_product_active(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(DEPOSITS, "html.parser")
    for c in soup.select(".product-card"):
        if "Мой доход" in c.get_text():
            c.decompose()
    pages.pages["savings_offers"] = str(soup)  # со страницы спецпредложений исчез, на странице вкладов остался
    events = [e for e in await run(seeded, tmp_path, pages) if e.change_type == "removed"]
    assert len(events) == 1 and events[0].severity == "info" and events[0].diff["placement_only"] is True
    async with seeded() as s:
        assert (await s.scalar(select(Product).where(Product.name == "Мой доход"))).is_active


async def test_product_returns_after_removal(seeded, tmp_path):
    from bs4 import BeautifulSoup
    pages = Pages()
    await run(seeded, tmp_path, pages)
    soup = BeautifulSoup(DEPOSITS, "html.parser")
    for c in soup.select(".product-card"):
        if "Социальный вклад" in c.get_text():
            c.decompose()
    pages.pages["deposits"] = pages.pages["savings_offers"] = str(soup)
    await run(seeded, tmp_path, pages)
    pages.pages["deposits"] = pages.pages["savings_offers"] = DEPOSITS
    events = await run(seeded, tmp_path, pages)
    back = [e for e in events if e.change_type == "new" and e.diff.get("returned")]
    assert back and back[0].severity == "rate"
    async with seeded() as s:
        assert (await s.scalar(select(Product).where(Product.name == "Социальный вклад"))).is_active
        assert "вернулся на сайт" in [c["text"] for c in await recent_changes(s, EPOCH) if c["diff"].get("returned")][0]


async def test_detect_changes_is_idempotent(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    pages.pages["deposits"] = mutate(DEPOSITS, "От 12,00% до 14,10%", "От 13,00% до 15,10%")
    await run(seeded, tmp_path, pages)
    async with seeded() as s:
        from bankintel.db.models import CollectionRun
        last = await s.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        before = len((await s.scalars(select(ChangeEvent))).all())
        again = await detect_changes(s, last)
        assert len(again) and len((await s.scalars(select(ChangeEvent))).all()) == before


async def test_condition_changes_from_detail_pages(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    async with seeded() as s:
        bank = await _psb(s)
        await collect_details(s, bank, pages, tmp_path)           # базовая линия условий
        pages.detail = mutate(DETAIL, "Льготное, если вклад закрывается после 90 дней, выплачивается ½ ставки", "Ставка 0,01% годовых")
        await collect_details(s, bank, pages, tmp_path)
        ev = (await s.scalars(select(ChangeEvent).where(ChangeEvent.change_type == "changed"))).all()
        cond = [e for e in ev if e.diff["kind"] == "conditions"]
        assert cond and cond[0].severity == "conditions"
        assert cond[0].diff["fields"][0]["label"] == "Условие «Досрочное расторжение»"
        assert "Ставка 0,01% годовых" in cond[0].diff["fields"][0]["new"]


async def test_recent_changes_window_and_severity_filter(seeded, tmp_path):
    pages = Pages()
    await run(seeded, tmp_path, pages)
    pages.pages["deposits"] = mutate(mutate(DEPOSITS, "Доступен для всех", "Доступен для всех клиентов"), "От 12,00% до 14,10%", "От 9% до 10%")
    await run(seeded, tmp_path, pages)
    async with seeded() as s:
        everything = await recent_changes(s, EPOCH)
        assert len(everything) >= 1
        assert await recent_changes(s, datetime.now(UTC) + timedelta(days=1)) == []
        assert all(c["severity"] == "rate" for c in await recent_changes(s, EPOCH, min_severity="rate"))
