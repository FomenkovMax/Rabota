"""Нормализованные факты о продукте для расчётов. Каждый факт прослеживается до снимков и документов."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.analytics.parsing import MoneyRange, TermSpec, parse_money_range, parse_term
from bankintel.db.models import Bank, Document, Product, ProductSnapshot, RegionAvailability

_FLOATING = re.compile(r"ключев", re.I)
# Признаки того, что максимальная ставка доступна не всем: категория клиентов или обязательное условие.
_RESTRICTED = re.compile(
    r"для (участников|получателей|новых|клиентов|пенсионер|военн|владельц)|только для|на новые|новых вкладчик|при отсутствии"
    r"|на специальных условиях|инвестируйте|в паи|купите",
    re.I,
)
_LIMITED = re.compile(r"\bдо \d{1,2} (январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)", re.I)
_CURRENCY_WORDS = (("рубл", "RUB"), ("юан", "CNY"), ("доллар", "USD"), ("евро", "EUR"))


@dataclass
class ProductFacts:
    product_id: int | None
    bank_slug: str
    bank_name: str
    is_benchmark: bool
    name: str
    category: str
    currency: str | None
    rate_min: Decimal | None
    rate_max: Decimal | None
    rate_text: str | None
    base_rate_max: Decimal | None
    amount: MoneyRange | None
    term: TermSpec | None
    term_text: str | None
    flags: list[str] = field(default_factory=list)  # floating_rate, restricted_audience
    notes: list[str] = field(default_factory=list)  # расхождения источников и т.п.
    lnr_status: str = "unknown"
    product_url: str | None = None
    checked_at: datetime | None = None
    snapshot_ids: list[int] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)


def _dec(v) -> Decimal | None:
    return Decimal(v) if v is not None else None


def _currency_from_words(text: str | None) -> str | None:
    t = (text or "").lower()
    return next((code for word, code in _CURRENCY_WORDS if word in t), None)


def _merge_money(card: MoneyRange | None, detail: MoneyRange | None, notes: list[str]) -> MoneyRange | None:
    if card is None or detail is None:
        return detail or card
    lo, hi = card.min if card.min is not None else detail.min, card.max if card.max is not None else detail.max
    for label, a, b in (("мин. сумма", card.min, detail.min), ("макс. сумма", card.max, detail.max)):
        if a is not None and b is not None and a != b:
            notes.append(f"{label}: карточка {a}, страница продукта {b} (взято значение страницы продукта)")
            lo, hi = (detail.min, hi) if label.startswith("мин") else (lo, detail.max)
    return MoneyRange(lo, hi, card.currency or detail.currency)


def _stricter_term(a: TermSpec, b: TermSpec) -> TermSpec:
    """Если один вариант — конкретные сроки, целиком лежащие в диапазоне другого, он строже."""
    for vals, rng in ((a, b), (b, a)):
        if vals.values and rng.min_days is not None and all(rng.min_days <= v <= rng.max_days for v in vals.values):
            return vals
    return b


def facts_from_params(
    *, bank: dict, product: dict, card: dict, conditions: dict | None = None
) -> ProductFacts:
    """Чистая функция: params снимков -> факты. bank: slug,name,is_benchmark; product: id,name,category."""
    notes: list[str] = []
    cond = (conditions or {}).get("conditions", {}) if conditions else {}

    rate = card.get("headline_rate_pct") or {}
    base = card.get("base_rate_pct") or {}

    card_term = parse_term(card.get("term_text"))
    detail_term_text = cond.get("term")
    detail_term = parse_term(detail_term_text)
    term, term_text = detail_term or card_term, (detail_term_text if detail_term else card.get("term_text"))
    if detail_term and card_term and detail_term != card_term:
        # при расхождении берём более строгий вариант (набор значений внутри диапазона), иначе — страницу продукта
        stricter = _stricter_term(card_term, detail_term)
        if stricter is card_term:
            term, term_text = card_term, card.get("term_text")
        notes.append(
            f"срок: карточка «{card.get('term_text')}», страница продукта «{detail_term_text}» "
            f"(использован {'вариант карточки' if stricter is card_term else 'вариант страницы продукта'})"
        )

    amount = _merge_money(parse_money_range(card.get("amount_text")), parse_money_range(cond.get("min_amount")), notes)
    currency = card.get("currency") or (amount.currency if amount else None) or _currency_from_words(cond.get("currency"))

    text = f"{card.get('title', '')} {card.get('description') or ''}"
    flags = []
    if _FLOATING.search(text):
        flags.append("floating_rate")
    if _LIMITED.search(text):
        flags.append("limited_time")
    if _RESTRICTED.search(text):
        flags.append("restricted_audience")

    return ProductFacts(
        product_id=product.get("id"), bank_slug=bank["slug"], bank_name=bank["name"], is_benchmark=bank.get("is_benchmark", False),
        name=product["name"], category=product["category"], currency=currency,
        rate_min=_dec(rate.get("min")), rate_max=_dec(rate.get("max")), rate_text=card.get("headline_rate_text"),
        base_rate_max=_dec(base.get("max")), amount=amount, term=term, term_text=term_text,
        flags=flags, notes=notes, product_url=card.get("product_url"),
    )


async def load_facts(session: AsyncSession, *, category: str | None = None) -> list[ProductFacts]:
    """Факты по всем активным продуктам из последних снимков."""
    out: list[ProductFacts] = []
    rows = (
        await session.execute(
            select(Product, Bank).join(Bank, Bank.id == Product.bank_id).where(Product.is_active)
            .order_by(Bank.id, Product.id)
        )
    ).all()
    for product, bank in rows:
        if category and product.category != category:
            continue
        snaps = (
            await session.scalars(select(ProductSnapshot).where(ProductSnapshot.product_id == product.id).order_by(ProductSnapshot.id.desc()))
        ).all()
        cards = [s for s in snaps if s.params.get("kind", "card") == "card"]
        if not cards:
            continue
        # основная карточка: со страницы списка вкладов/счетов, иначе самая свежая
        card = next((s for s in cards if s.params.get("page_key") in ("deposits", "savings_accounts")), cards[0])
        detail = next((s for s in snaps if s.params.get("kind") == "conditions"), None)
        facts = facts_from_params(
            bank={"slug": bank.slug, "name": bank.name, "is_benchmark": bank.is_benchmark},
            product={"id": product.id, "name": product.name, "category": product.category},
            card=card.params, conditions=detail.params if detail else None,
        )
        used = [s for s in (card, detail) if s]
        facts.snapshot_ids = [s.id for s in used]
        facts.document_ids = [s.document_id for s in used]
        docs = (await session.scalars(select(Document).where(Document.id.in_(facts.document_ids)))).all()
        facts.checked_at = min((d.fetched_at for d in docs), default=None)
        av = await session.scalar(select(RegionAvailability).where(RegionAvailability.product_id == product.id))
        facts.lnr_status = av.status if av else "unknown"
        out.append(facts)
    return out
