"""Единый набор данных отчёта.

Все четыре формата (HTML, PDF, PPTX, XLSX) строятся из одного словаря `build_dataset(...)`.
Он содержит только JSON-совместимые значения (деньги — строками Decimal), проверяется
`validate_dataset` до рендеринга и получает `dataset_id` — отпечаток содержимого, который
печатается в каждом файле: по нему видно, что файлы построены из одних и тех же данных.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel import __version__
from bankintel.analytics.compare import DEFAULT_SCENARIOS, Scenario, ScenarioResult, compare
from bankintel.analytics.facts import ProductFacts, load_facts
from bankintel.db.models import Bank, CollectionRun, Document, FetchAttempt, Source
from bankintel.formatting import money, pct
from bankintel.monitor import monitoring_status, recent_changes

METHOD_VERSION = "1"
_SYNTHETIC = re.compile(r"synthetic|example\.(com|org)|\.test\b|тестов", re.I)

LIMITATIONS = [
    "Доступность продуктов в ЛНР НЕ подтверждена ни одним источником: общероссийские страницы банков не доказывают доступность в регионе.",
    "Сбербанк (эталон сравнения) отсутствует: его сайт недоступен автоматическому сбору, ручной импорт документов не выполнен. Сравнения со Сбером в отчёте нет.",
    "Расчёт дохода — простой процент по номинальной ставке с сайта, до налогов, без капитализации. Фактическая ставка зависит от срока, суммы и условий, поэтому показан интервал.",
    "Условия вкладов ВТБ (срок, капитализация, пополнение) со страниц продуктов не извлечены; часть вкладов ВТБ исключена из сценариев с указанием причины.",
    "Признаки «особых условий» определяются по тексту описаний и могут быть неполными.",
    "Отчёт — демонстрационный прототип; решения по продуктам на его основе принимать нельзя без ручной проверки по источникам.",
]
METHODOLOGY = [
    "Данные собраны с официальных страниц банков (конфигурация источников подтверждена владельцем проекта); исходные документы сохранены с хешем и временем получения.",
    "Сценарий = сумма × срок. Месяцы переводятся в дни по правилу 365/12 с округлением вверх от половины (3→91, 6→183, 12→365).",
    "Доход = сумма × ставка% × дни / 365. Верхняя граница — по максимальной ставке сайта, нижняя — по минимальной, если она указана.",
    "Продукт исключается из сценария, если не подходят срок, сумма или валюта, либо срок/ставка не распознаны.",
    "В основной рейтинг входят предложения для всех клиентов; предложения с особыми условиями вынесены отдельно (на графиках — штриховка).",
    "Все вычисления выполнены программно (Decimal); нейросеть для расчётов не использовалась.",
    "Изменения определяются сравнением снимков одного и того же источника между запусками сбора; первый запуск — базовая линия. Продукт считается исчезнувшим, только если страница загрузилась и разобралась.",
]


def _no_data_reason(bank: Bank, last_fetch: dict | None, manual_docs: int) -> str:
    if last_fetch and last_fetch["outcome"] in ("blocked", "robots_disallowed", "tls_error"):
        return f"сайт недоступен автоматическому сбору ({last_fetch['outcome']}); ручной импорт документов не выполнен" if not manual_docs else "документы импортированы вручную, адаптер не реализован"
    if last_fetch and last_fetch["outcome"] in ("http_error", "network_error", "too_large"):
        return f"сайт не отдал данные ({last_fetch['outcome']})" + (f": {last_fetch['error']}" if last_fetch.get("error") else "")
    if bank.adapter == "generic":
        return "адаптер банка не реализован: источники продуктовых страниц не подтверждены"
    return "данные не собирались"


def _coverage_reason(bank: Bank, n: dict, last_fetch: dict | None, manual_docs: int) -> str | None:
    if not (n["deposit"] or n["savings"]):
        return _no_data_reason(bank, last_fetch, manual_docs)
    if last_fetch and last_fetch["outcome"] != "ok":
        return f"последняя загрузка не удалась ({last_fetch['outcome']}) — данные взяты из ранее сохранённых и могут быть устаревшими"
    return None


def _row(r: ScenarioResult) -> dict:
    f = r.facts
    return {
        "bank": f.bank_name, "bank_slug": f.bank_slug, "name": f.name,
        "rate_text": f.rate_text, "rate_min": _s(f.rate_min), "rate_max": _s(f.rate_max),
        "income_min": _s(r.income_min), "income_max": _s(r.income_max),
        "term_text": f.term_text, "flags": sorted(f.flags), "warnings": r.warnings,
        "lnr_status": f.lnr_status, "product_url": f.product_url,
        "checked_at": f.checked_at.isoformat() if f.checked_at else None, "document_ids": f.document_ids,
    }


def _s(x: Decimal | None) -> str | None:
    return None if x is None else str(x)


def _product(f: ProductFacts) -> dict:
    return {
        "bank": f.bank_name, "bank_slug": f.bank_slug, "name": f.name, "category": f.category,
        "currency": f.currency, "rate_text": f.rate_text, "rate_min": _s(f.rate_min), "rate_max": _s(f.rate_max),
        "base_rate_max": _s(f.base_rate_max), "term_text": f.term_text,
        "amount_min": _s(f.amount.min) if f.amount else None, "amount_max": _s(f.amount.max) if f.amount else None,
        "flags": sorted(f.flags), "notes": f.notes, "lnr_status": f.lnr_status, "product_url": f.product_url,
        "checked_at": f.checked_at.isoformat() if f.checked_at else None,
        "snapshot_ids": f.snapshot_ids, "document_ids": f.document_ids,
    }


def _scenario_block(facts: list[ProductFacts], sc: Scenario, banks, now) -> dict:
    rep = compare(facts, sc, all_banks=banks, now=now)
    best = rep.best_by_bank()
    gap = None
    if len(best) >= 2:
        a, b = sorted(best.values(), key=lambda r: r.income_max, reverse=True)[:2]
        gap = {"leader": a.facts.bank_name, "second": b.facts.bank_name, "amount": str(a.income_max - b.income_max)}
    return {
        "amount": str(sc.amount), "months": sc.months, "days": sc.days,
        "label": f"{money(sc.amount)} на {sc.months} мес.",
        "open": [_row(r) for r in rep.eligible_open], "restricted": [_row(r) for r in rep.eligible_restricted],
        "best_open_by_bank": [_row(r) for r in best.values()],
        "excluded": [{"bank": r.facts.bank_name, "name": r.facts.name, "reason": r.exclusion} for r in rep.excluded],
        "banks_without_data": rep.banks_without_data, "gap": gap,
    }


def _insights(scenarios: list[dict]) -> list[str]:
    out = []
    for s in scenarios:
        if s["gap"]:
            g = s["gap"]
            out.append(
                f"{s['label']}: среди предложений для всех клиентов по верхней границе дохода {g['leader']} опережает "
                f"{g['second']} на {money(g['amount'])}."
            )
        elif s["best_open_by_bank"]:
            r = s["best_open_by_bank"][0]
            out.append(f"{s['label']}: данные есть только по банку {r['bank']} — сравнивать не с чем.")
        else:
            out.append(f"{s['label']}: подходящих вкладов для всех клиентов нет.")
    return out


async def build_dataset(session: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    facts = await load_facts(session)
    banks = (await session.execute(select(Bank).order_by(Bank.is_benchmark.desc(), Bank.id))).scalars().all()
    bank_pairs = [(b.slug, b.name) for b in banks]

    coverage = []
    for b in banks:
        run = await session.scalar(select(CollectionRun).where(CollectionRun.bank_id == b.id).order_by(CollectionRun.id.desc()).limit(1))
        att = await session.scalar(
            select(FetchAttempt).join(Source, Source.id == FetchAttempt.source_id)
            .where(Source.bank_id == b.id).order_by(FetchAttempt.id.desc()).limit(1)
        )
        manual = await session.scalar(
            select(func.count(Document.id)).join(Source, Source.id == Document.source_id)
            .where(Source.bank_id == b.id, Document.origin == "manual_import")
        )
        n = {c: sum(1 for f in facts if f.bank_slug == b.slug and f.category == c) for c in ("deposit", "savings")}
        last_fetch = {"outcome": att.outcome, "at": att.attempted_at.isoformat(), "error": att.error} if att else None
        coverage.append({
            "reason": _coverage_reason(b, n, last_fetch, manual or 0),
            "slug": b.slug, "name": b.name, "is_benchmark": b.is_benchmark,
            "status": "data" if (n["deposit"] or n["savings"]) else "no_data",
            "deposits": n["deposit"], "savings": n["savings"], "manual_documents": manual or 0,
            "domain_verified": b.domain_verified, "lnr_presence_verified": b.lnr_presence_verified,
            "last_run": {"status": run.status, "at": run.started_at.isoformat(), "message": run.message} if run else None,
            "last_fetch": last_fetch,
        })

    scenarios = [_scenario_block(facts, sc, bank_pairs, now) for sc in DEFAULT_SCENARIOS]

    doc_ids = sorted({d for f in facts for d in f.document_ids})
    docs = (await session.execute(
        select(Document, Source, Bank).join(Source, Source.id == Document.source_id).join(Bank, Bank.id == Source.bank_id)
        .where(Document.id.in_(doc_ids)).order_by(Bank.id, Document.id)
    )).all() if doc_ids else []
    sources = [{
        "document_id": d.id, "bank": b.name, "source_key": s.key, "url": d.url, "origin": d.origin,
        "fetched_at": d.fetched_at.isoformat(), "sha256": d.sha256, "size_bytes": d.size_bytes,
    } for d, s, b in docs]

    stamps = [f.checked_at for f in facts if f.checked_at]
    products = [_product(f) for f in facts]
    window = 30
    changes = {
        "window_days": window, "monitoring": await monitoring_status(session),
        "items": [{k: c[k] for k in ("detected_at", "bank", "product", "type", "severity", "text")}
                  for c in (await recent_changes(session, now - timedelta(days=window)))[:100]],
    }
    ds = {
        "changes": changes,
        "meta": {
            "title": "Banking Intelligence AI — конкурентный анализ вкладов и накопительных счетов",
            "region": "ЛНР", "app_version": __version__, "method_version": METHOD_VERSION,
            "data_from": min(stamps).isoformat() if stamps else None, "data_to": max(stamps).isoformat() if stamps else None,
            "products_total": len(products), "lnr_confirmed": sum(p["lnr_status"] == "confirmed" for p in products),
            "banks_with_data": sum(c["status"] == "data" for c in coverage), "banks_total": len(coverage),
        },
        "coverage": coverage, "scenarios": scenarios, "insights": _insights(scenarios),
        "catalog": {"deposit": [p for p in products if p["category"] == "deposit"],
                    "savings": [p for p in products if p["category"] == "savings"]},
        "sources": sources, "methodology": METHODOLOGY, "limitations": LIMITATIONS,
    }
    validate_dataset(ds)
    ds["meta"]["dataset_id"] = dataset_id(ds)
    ds["meta"]["generated_at"] = now.isoformat()
    return ds


def dataset_id(ds: dict) -> str:
    body = {k: v for k, v in ds.items() if k != "meta"}
    body["meta"] = {k: v for k, v in ds["meta"].items() if k not in ("dataset_id", "generated_at")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


class DatasetError(Exception):
    pass


def validate_dataset(ds: dict) -> None:
    """Отчёт не строится из данных, которые нельзя проследить до источника или которые похожи на демо-данные."""
    errors = []
    products = ds["catalog"]["deposit"] + ds["catalog"]["savings"]
    if not products:
        errors.append("нет ни одного продукта: сначала выполните сбор данных (bankintel refresh)")
    known_docs = {s["document_id"] for s in ds["sources"]}
    for p in products:
        who = f"{p['bank']} / {p['name']}"
        if not p["document_ids"] or not set(p["document_ids"]) <= known_docs:
            errors.append(f"{who}: нет ссылки на сохранённый документ")
        if not p["checked_at"]:
            errors.append(f"{who}: неизвестна дата проверки")
        if _SYNTHETIC.search(f"{p['name']} {p.get('product_url') or ''}"):
            errors.append(f"{who}: похоже на тестовые данные")
        for k in ("rate_min", "rate_max"):
            if p[k] is not None and not (Decimal(0) <= Decimal(p[k]) <= Decimal(100)):
                errors.append(f"{who}: {k}={p[k]} вне 0–100%")
    for s in ds["scenarios"]:
        for r in s["open"] + s["restricted"]:
            if Decimal(r["income_max"]) < 0 or (r["income_min"] is not None and Decimal(r["income_min"]) > Decimal(r["income_max"])):
                errors.append(f"{s['label']} / {r['name']}: некорректный интервал дохода")
    if errors:
        raise DatasetError("Набор данных не прошёл проверку:\n- " + "\n- ".join(errors))


def fmt_dt(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M") if iso else "—"


def fmt_date(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y") if iso else "—"


__all__ = ["build_dataset", "validate_dataset", "DatasetError", "dataset_id", "fmt_dt", "fmt_date", "money", "pct"]
