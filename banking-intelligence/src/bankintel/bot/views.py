"""Формирование текстов ответов (HTML parse mode) из данных БД."""

from html import escape

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, CollectionRun, Document, FetchAttempt, Product, Source

DEMO_NOTICE = "⚠️ Демо-прототип. Данные ещё не собирались — цифр здесь нет намеренно."

# Команда -> (название, этап, в чём суть). Пока не реализовано — честно говорим об этом.
PLANNED = {
    "compare": ("Сравнение со Сбером", 4),
    "deposits": ("Вклады", 2),
    "savings": ("Накопительные счета", 2),
    "promo": ("Акции", 2),
    "changes": ("История изменений", 6),
    "report": ("Отчёты PDF/HTML/PPTX/XLSX", 5),
}


def start_text() -> str:
    return (
        "<b>Banking Intelligence AI</b>\n"
        "Конкурентный анализ розничных банковских продуктов в ЛНР.\n\n"
        f"{DEMO_NOTICE}\n\n"
        "/banks — реестр банков\n"
        "/status — состояние данных\n"
        "/compare /deposits /savings /promo /changes /report /refresh — "
        "в разработке (см. PLANS.md)"
    )


def planned_text(command: str) -> str:
    title, stage = PLANNED[command]
    return f"🚧 <b>{escape(title)}</b> пока не реализовано (этап {stage} из PLANS.md).\n{DEMO_NOTICE}"


async def banks_text(session: AsyncSession) -> str:
    banks = (await session.scalars(select(Bank).order_by(Bank.is_benchmark.desc(), Bank.name))).all()
    if not banks:
        return "Реестр банков пуст. Выполните <code>bankintel seed</code>."
    lines = ["<b>Банки в реестре</b>"]
    for b in banks:
        flags = []
        flags.append("домен ✅" if b.domain_verified else "домен ⚠️ не подтверждён")
        flags.append("ЛНР ✅" if b.lnr_presence_verified else "ЛНР ⚠️ не подтверждено")
        mark = "⭐ " if b.is_benchmark else ""
        lines.append(f"{mark}<b>{escape(b.name)}</b> — {escape(b.website)}\n   {', '.join(flags)}")
    lines.append("\n⚠️ — требует ручного подтверждения; до этого данные банка считаются предварительными.")
    return "\n".join(lines)


async def status_text(session: AsyncSession) -> str:
    banks = (await session.scalars(select(Bank).order_by(Bank.name))).all()
    if not banks:
        return "Реестр банков пуст. Выполните <code>bankintel seed</code>."
    lines = ["<b>Состояние данных</b>"]
    for b in banks:
        run = await session.scalar(
            select(CollectionRun).where(CollectionRun.bank_id == b.id).order_by(CollectionRun.id.desc()).limit(1)
        )
        docs = await session.scalar(
            select(func.count(Document.id)).join(Source, Source.id == Document.source_id).where(Source.bank_id == b.id)
        )
        products = await session.scalar(select(func.count(Product.id)).where(Product.bank_id == b.id))
        if run is None:
            state = "сбор не запускался"
        else:
            when = run.started_at.strftime("%d.%m.%Y %H:%M")
            state = f"последний сбор {when}: {run.status}"
        last = await session.scalar(
            select(FetchAttempt).join(Source, Source.id == FetchAttempt.source_id)
            .where(Source.bank_id == b.id).order_by(FetchAttempt.id.desc()).limit(1)
        )
        diag = f"\n   последняя загрузка: {last.outcome}" + (f" ({escape(last.error[:120])})" if last and last.error else "") if last else ""
        lines.append(f"<b>{escape(b.name)}</b>: {state}; документов {docs}, продуктов {products}{diag}")
    return "\n".join(lines)


def refresh_text(results) -> str:
    lines = ["<b>Результат обновления</b>"]
    for bank, run in results:
        note = f" — {escape(run.message)}" if run.message else ""
        lines.append(f"{escape(bank.name)}: <b>{run.status}</b>{note}")
    if all(r.status == "failed" and "Нет активных" in (r.message or "") for _, r in results):
        lines.append("\nАктивных источников нет: URL продуктовых страниц ещё не подтверждены вручную (PLANS.md, этап 2).")
    return "\n".join(lines)
