"""Тексты команд /compare, /deposits, /savings. Числа приходят из analytics (Decimal), здесь только форматирование."""

from decimal import Decimal
from html import escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.analytics.compare import ComparisonReport, Scenario, compare
from bankintel.analytics.facts import ProductFacts, load_facts
from bankintel.db.models import Bank
from bankintel.formatting import money, pct  # noqa: F401

MAX_AMOUNT = Decimal(1_000_000_000)
LNR_NOTE = "доступность в ЛНР не подтверждена источниками"
METHOD_NOTE = (
    "Доход — простой процент по номинальной ставке с сайта (факт. дни/365), до налогов и без капитализации. "
    "Ставки на сайтах — диапазоны, поэтому показан интервал."
)


def parse_scenario(args: str | None) -> Scenario:
    """'/compare' -> по умолчанию; '/compare 1000000 6' -> сумма и срок в месяцах."""
    if not args or not args.strip():
        return Scenario(Decimal(500_000), 12)
    parts = args.replace("_", "").split()
    if len(parts) != 2:
        raise ValueError("Формат: /compare <сумма в ₽> <срок в месяцах>, например /compare 500000 12")
    try:
        amount, months = Decimal(parts[0]), int(parts[1])
    except Exception:
        raise ValueError("Сумма и срок должны быть числами: /compare 500000 12") from None
    if not (Decimal(1000) <= amount <= MAX_AMOUNT) or not (1 <= months <= 60):
        raise ValueError("Допустимо: сумма 1 000 – 1 000 000 000 ₽, срок 1–60 месяцев")
    return Scenario(amount, months)


def _rate(f: ProductFacts) -> str:
    if f.rate_max is None:
        return "ставка не распознана"
    if f.rate_min is None:
        return f"до {pct(f.rate_max)}"
    return pct(f.rate_max) if f.rate_min == f.rate_max else f"{pct(f.rate_min)}–{pct(f.rate_max)}"


def _flags(f: ProductFacts) -> str:
    out = []
    if "restricted_audience" in f.flags:
        out.append("👥 особые условия/категория клиентов")
    if "floating_rate" in f.flags:
        out.append("📈 плавающая")
    if "ai_assisted" in f.flags:
        out.append("🤖 часть данных извлечена AI")
    if "limited_time" in f.flags:
        out.append("⏳ ограничено по времени")
    return (" " + ", ".join(out)) if out else ""


def compare_text(rep: ComparisonReport) -> str:
    sc = rep.scenario
    lines = [f"📊 <b>Сравнение вкладов: {money(sc.amount)} на {sc.months} мес.</b> ({sc.days} дн.)", f"<i>{METHOD_NOTE}</i>", ""]
    best = rep.best_by_bank()
    if not best:
        lines.append("Подходящих вкладов без особых условий в этом сценарии нет.")
    else:
        lines.append("<b>Лучший вклад по банкам</b> — для всех клиентов, по верхней границе дохода")
        for r in best.values():
            lines.append(_line(r))
    for name in rep.banks_without_data:
        lines.append(f"• <b>{escape(name)}</b> — данных нет")
    if len(best) >= 2:
        a, b = sorted(best.values(), key=lambda r: r.income_max, reverse=True)[:2]
        lines.append(
            f"\nРазрыв по верхней границе: {escape(a.facts.bank_name)} выше {escape(b.facts.bank_name)} "
            f"на {money(a.income_max - b.income_max)}"
        )
    restricted = rep.best_by_bank(restricted=True)
    if restricted:
        lines.append("\n<b>С особыми условиями</b> (не для всех: категория клиентов или обязательное условие)")
        for r in restricted.values():
            lines.append(_line(r))
    open_top = rep.eligible_open[:5]
    if len(open_top) > 1:
        lines.append("\n<b>Топ-5 вкладов для всех</b>")
        for r in open_top:
            f = r.facts
            lines.append(f"{escape(f.bank_name)} · {escape(f.name)}: до {money(r.income_max)} ({_rate(f)}){_flags(f)}")
    if rep.excluded:
        lines.append(f"\nИсключено {len(rep.excluded)} из {len(rep.results)} вкладов (срок, сумма, валюта или данные не подходят). Подробности: /deposits")
    if rep.eligible and any(r.facts.lnr_status != "confirmed" for r in rep.eligible):
        lines.append(f"\n⚠️ У показанных продуктов {LNR_NOTE}.")
    return "\n".join(lines).strip()


def _line(r) -> str:
    f = r.facts
    lo = f"{money(r.income_min)} – " if r.income_min is not None else "до "
    return f"• <b>{escape(f.bank_name)}</b> — {escape(f.name)}: {lo}{money(r.income_max)} ({_rate(f)}){_flags(f)}"


def deposits_text(facts: list[ProductFacts]) -> str:
    return _catalog(facts, "deposit", "💰 <b>Вклады</b>")


def savings_text(facts: list[ProductFacts]) -> str:
    return _catalog(facts, "savings", "🏦 <b>Накопительные счета</b>") + (
        "\n\n<i>«До X%» — максимум при выполнении условий банка (бонусы, временные периоды). "
        "Доход по счетам не рассчитываем.</i>"
    )


def _catalog(facts: list[ProductFacts], category: str, title: str) -> str:
    rows = [f for f in facts if f.category == category]
    if not rows:
        return f"{title}\nДанных нет. Выполните сбор: <code>bankintel refresh</code>."
    lines = [title, "<i>Ставки и условия — как опубликовано на сайтах банков; это не гарантия для конкретной суммы и срока.</i>"]
    bank = None
    for f in rows:
        if f.bank_name != bank:
            bank = f.bank_name
            lines.append(f"\n<b>{escape(bank)}</b>")
        extra = []
        if f.term_text and category == "deposit":
            extra.append(f"срок {escape(f.term_text)}")
        if f.amount and (f.amount.min is not None or f.amount.max is not None):
            lo = f"от {money(f.amount.min)}" if f.amount.min is not None else ""
            hi = f"до {money(f.amount.max)}" if f.amount.max is not None else ""
            extra.append(" ".join(x for x in (lo, hi) if x).replace(" ₽", "") + (f" {f.currency}" if f.currency else ""))
        if f.base_rate_max is not None:
            extra.append(f"базовая {pct(f.base_rate_max)}")
        tail = f" · {'; '.join(extra)}" if extra else ""
        mark = " ℹ️ источники расходятся" if f.notes and "ai_assisted" not in f.flags else ""
        lines.append(f"• {escape(f.name)}: {_rate(f)}{tail}{_flags(f)}{mark}")
    lines.append(f"\n⚠️ {LNR_NOTE[0].upper() + LNR_NOTE[1:]}.")
    return "\n".join(lines)


async def load_for_bot(session: AsyncSession):
    facts = await load_facts(session)
    banks = (await session.execute(select(Bank.slug, Bank.name).order_by(Bank.is_benchmark.desc(), Bank.id))).all()
    return facts, [(s, n) for s, n in banks]


async def compare_for_bot(session: AsyncSession, scenario: Scenario) -> str:
    facts, banks = await load_for_bot(session)
    return compare_text(compare(facts, scenario, all_banks=banks))
