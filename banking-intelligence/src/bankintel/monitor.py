"""Мониторинг изменений: сравнение снимков текущего запуска с предыдущим по каждому источнику.

Правила против ложных срабатываний:
 * первый запуск по источнику — базовая линия, событий нет;
 * сравнение идёт внутри одного источника (одна страница), поэтому расхождения между страницами
   не считаются изменениями;
 * «продукт исчез» — только если страница в этом запуске загрузилась и разобралась
   (есть снимки этого источника); сбой загрузки/разбора ничего не «удаляет»;
 * значимость: rate (ставка/срок/сумма/валюта) > conditions (условия) > info (текст).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, ChangeEvent, CollectionRun, Document, Product, ProductSnapshot, Source
from bankintel.domain.enums import ChangeType
from bankintel.sources.common import FAQ_PREFIX

SEVERITY_ORDER = {"info": 0, "conditions": 1, "rate": 2}
# поле params карточки -> (подпись, значимость)
CARD_FIELDS = {
    "headline_rate_text": ("Ставка", "rate"), "headline_rate_label": ("Подпись ставки", "info"),
    "base_rate_text": ("Базовая ставка", "rate"), "yield_text": ("Доходность", "rate"),
    "term_text": ("Срок", "rate"), "amount_text": ("Сумма", "rate"), "currency": ("Валюта", "rate"),
    "title": ("Название", "info"), "description": ("Описание", "info"), "product_url": ("Ссылка", "info"),
}


@dataclass
class FieldChange:
    label: str
    old: str | None
    new: str | None
    severity: str


def _as_text(v) -> str | None:
    return None if v is None else str(v)


def diff_card(old: dict, new: dict) -> list[FieldChange]:
    out = [
        FieldChange(label, _as_text(old.get(k)), _as_text(new.get(k)), sev)
        for k, (label, sev) in CARD_FIELDS.items()
        if old.get(k) != new.get(k)
    ]
    if not out and old.get("advantages") != new.get("advantages"):  # прочие параметры карточки
        out.append(FieldChange("Параметры карточки", _fmt_adv(old.get("advantages")), _fmt_adv(new.get("advantages")), "info"))
    return out


def _fmt_adv(adv) -> str | None:
    return "; ".join(f"{a['label']}: {a['value']}" for a in adv) if adv else None


def diff_conditions(old: dict, new: dict) -> list[FieldChange]:
    o = {r["label"]: r["value"] for r in old.get("conditions_raw", [])}
    n = {r["label"]: r["value"] for r in new.get("conditions_raw", [])}
    out = []
    for label in list(dict.fromkeys([*o, *n])):
        if o.get(label) != n.get(label):
            if label.startswith(FAQ_PREFIX):
                sev = "info"  # свободный текст FAQ без разбора: правки формулировок не считаем изменением условий
            else:
                sev = "rate" if label.lower().startswith(("ставка", "базовая ставка")) else "conditions"
            out.append(FieldChange(f"Условие «{label}»", o.get(label), n.get(label), sev))
    return out


def rate_direction(old: dict, new: dict) -> str | None:
    """'up' / 'down' по верхней границе ставки, если обе распознаны."""
    try:
        a, b = old["headline_rate_pct"]["max"], new["headline_rate_pct"]["max"]
        a, b = Decimal(a), Decimal(b)
    except Exception:
        return None
    return "up" if b > a else "down" if b < a else None


def _max_severity(items: list[FieldChange]) -> str:
    return max((i.severity for i in items), key=SEVERITY_ORDER.__getitem__, default="info")


async def _latest_by_product(session, source_id: int, run_id: int) -> dict[int, ProductSnapshot]:
    rows = (
        await session.scalars(
            select(ProductSnapshot).join(Document, Document.id == ProductSnapshot.document_id)
            .where(Document.source_id == source_id, ProductSnapshot.run_id == run_id).order_by(ProductSnapshot.id)
        )
    ).all()
    return {r.product_id: r for r in rows}  # последний снимок продукта в запуске


async def _still_listed_elsewhere(session, product_id: int, except_source: int) -> bool:
    """Есть ли продукт в самом свежем запуске какого-либо другого источника."""
    rows = (
        await session.execute(
            select(Document.source_id, func.max(ProductSnapshot.run_id))
            .join(Document, Document.id == ProductSnapshot.document_id)
            .where(ProductSnapshot.product_id == product_id, Document.source_id != except_source, ProductSnapshot.run_id.is_not(None))
            .group_by(Document.source_id)
        )
    ).all()
    for source_id, last_run in rows:
        newest = await session.scalar(
            select(func.max(ProductSnapshot.run_id)).join(Document, Document.id == ProductSnapshot.document_id).where(Document.source_id == source_id)
        )
        if last_run == newest:
            return True
    return False


async def detect_changes(session: AsyncSession, run: CollectionRun) -> list[ChangeEvent]:
    """Создаёт события изменений для запуска. Идемпотентно: повторный вызов возвращает уже созданные."""
    existing = (await session.scalars(select(ChangeEvent).where(ChangeEvent.run_id == run.id))).all()
    if existing:
        return list(existing)

    cur_rows = (
        await session.execute(
            select(Document.source_id).join(ProductSnapshot, ProductSnapshot.document_id == Document.id)
            .where(ProductSnapshot.run_id == run.id).distinct()
        )
    ).all()
    events: list[ChangeEvent] = []
    for (source_id,) in cur_rows:
        prev_run = await session.scalar(
            select(func.max(ProductSnapshot.run_id)).join(Document, Document.id == ProductSnapshot.document_id)
            .where(Document.source_id == source_id, ProductSnapshot.run_id < run.id)
        )
        if prev_run is None:
            continue  # базовая линия: сравнивать не с чем
        source = await session.get(Source, source_id)
        cur = await _latest_by_product(session, source_id, run.id)
        prev = await _latest_by_product(session, source_id, prev_run)

        for pid in cur.keys() - prev.keys():
            product = await session.get(Product, pid)
            earlier = await session.scalar(
                select(func.count(ProductSnapshot.id)).where(ProductSnapshot.product_id == pid, ProductSnapshot.run_id < run.id)
            )
            brand_new = not earlier
            returned = bool(earlier) and not product.is_active  # был снят с сайта и вернулся
            product.is_active = True
            events.append(_event(pid, run, ChangeType.NEW, "rate" if (brand_new or returned) else "info", cur[pid],
                                 {"source_key": source.key, "placement_only": not (brand_new or returned), "returned": returned}))
        for pid in prev.keys() - cur.keys():
            product = await session.get(Product, pid)
            gone = not await _still_listed_elsewhere(session, pid, source_id)
            if gone:
                product.is_active = False
            events.append(_event(pid, run, ChangeType.REMOVED, "rate" if gone else "info", prev[pid],
                                 {"source_key": source.key, "placement_only": not gone}))
        for pid in cur.keys() & prev.keys():
            o, n = prev[pid].params, cur[pid].params
            kind = n.get("kind", "card")
            changes = diff_conditions(o, n) if kind == "conditions" else diff_card(o, n)
            if changes:
                diff = {"source_key": source.key, "kind": kind, "direction": rate_direction(o, n) if kind == "card" else None,
                        "fields": [c.__dict__ for c in changes]}
                events.append(_event(pid, run, ChangeType.CHANGED, _max_severity(changes), cur[pid], diff))
    session.add_all(events)
    await session.commit()
    return events


def _event(product_id: int, run: CollectionRun, kind: ChangeType, severity: str, snap: ProductSnapshot, diff: dict) -> ChangeEvent:
    return ChangeEvent(product_id=product_id, run_id=run.id, change_type=kind.value, severity=severity, snapshot_id=snap.id, diff=diff)


# ---------- человекочитаемое описание ----------

ARROW = {"up": "↑", "down": "↓", None: ""}


def describe(event: ChangeEvent, product_name: str, bank_name: str) -> str:
    d = event.diff or {}
    head = f"{bank_name} · {product_name}"
    if event.change_type == "new":
        where = f" на странице «{d.get('source_key')}»" if d.get("placement_only") else ""
        what = "вернулся на сайт" if d.get("returned") else "новый продукт"
        return f"{head}: {'появился в списке' + where if d.get('placement_only') else what}"
    if event.change_type == "removed":
        where = f" со страницы «{d.get('source_key')}»" if d.get("placement_only") else ""
        return f"{head}: {'исчез из списка' + where if d.get('placement_only') else 'продукт исчез с сайта'}"
    parts = [f"{f['label']}: «{f['old'] or '—'}» → «{f['new'] or '—'}»" for f in d.get("fields", [])]
    return f"{head}: {ARROW.get(d.get('direction'), '')} " + "; ".join(parts)


async def recent_changes(session: AsyncSession, since: datetime, *, min_severity: str = "info") -> list[dict]:
    rows = (
        await session.execute(
            select(ChangeEvent, Product, Bank).join(Product, Product.id == ChangeEvent.product_id).join(Bank, Bank.id == Product.bank_id)
            .where(ChangeEvent.detected_at >= since).order_by(ChangeEvent.detected_at.desc(), ChangeEvent.id.desc())
        )
    ).all()
    floor = SEVERITY_ORDER[min_severity]
    out = []
    for ev, product, bank in rows:
        if SEVERITY_ORDER.get(ev.severity, 0) < floor:
            continue
        out.append({
            "detected_at": ev.detected_at.isoformat(), "bank": bank.name, "bank_slug": bank.slug, "product": product.name,
            "category": product.category, "type": ev.change_type, "severity": ev.severity, "run_id": ev.run_id,
            "text": describe(ev, product.name, bank.name), "diff": ev.diff,
        })
    return out


async def monitoring_status(session: AsyncSession) -> dict:
    """С какого момента ведётся наблюдение и было ли уже хоть одно сравнение (иначе «нет изменений» вводит в заблуждение).
    comparisons — сколько раз самый часто собираемый источник сравнивался с предыдущим состоянием; 0 = только базовая линия."""
    first = await session.scalar(select(func.min(CollectionRun.started_at)).where(CollectionRun.status.in_(("ok", "partial"))))
    last = await session.scalar(select(func.max(CollectionRun.started_at)).where(CollectionRun.status.in_(("ok", "partial"))))
    per_source = (
        await session.execute(
            select(func.count(func.distinct(ProductSnapshot.run_id))).join(Document, Document.id == ProductSnapshot.document_id)
            .where(ProductSnapshot.run_id.is_not(None)).group_by(Document.source_id)
        )
    ).scalars().all()
    return {"since": first.isoformat() if first else None, "last_run": last.isoformat() if last else None,
            "comparisons": max(max(per_source, default=0) - 1, 0), "has_data": bool(per_source)}


__all__ = ["detect_changes", "describe", "recent_changes", "monitoring_status", "diff_card", "diff_conditions", "UTC"]
