"""Проверка ответа модели кодом: цитата должна дословно присутствовать в документе, быть по теме, а числа значения — в цитате.
Модели не доверяем: непроверенное отбрасывается и записывается в rejected с причиной."""

import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import ValidationError

from bankintel.ai.schemas import AiConditions

MIN_QUOTE = 8
MAX_QUOTE = 400
# Цитата обязана касаться темы факта (лексическая защита от «верной» цитаты не про то).
TOPIC = {
    "capitalization": r"капитализ", "topup_allowed": r"пополн", "withdrawal_allowed": r"снят|расходн",
    "early_termination": r"досрочн|расторж", "payout": r"выплат|начисл|процент", "term": r"срок|мес|дн|год|лет",
    "min_amount": r"сумм|₽|руб|от \d|минимальн", "max_amount": r"сумм|₽|руб|до \d|максимальн",
}
LNR_MARKER = re.compile(r"\bлнр\b|луганск", re.I)
# Упоминание региона в контактах/уведомлениях — не утверждение о доступности продукта, что бы ни ответила модель.
NOT_AVAILABILITY_CLAIM = re.compile(r"звон|телефон|горяч|8 ?800|\+7|уведомлен", re.I)


# Цитата, похожая на указание модели, — вероятная prompt injection: проверка «цитата есть в тексте» её бы пропустила.
INJECTION = re.compile(
    r"игнорир|забудь|инструкци|верни |ответь|выведи|system prompt|ignore (all|previous|the)|disregard|you are |ты —|ты -|от имени|jailbreak|\bпромпт",
    re.I,
)


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).replace(" ", " ").replace(" ", " ")
    t = t.replace("«", '"').replace("»", '"').replace("—", "-").replace("–", "-")
    return " ".join(t.split()).casefold()


def _numbers(text: str) -> set[str]:
    return {n.replace(" ", "").replace(",", ".") for n in re.findall(r"\d[\d ]*(?:[.,]\d+)?", normalize(text))}


@dataclass
class Verified:
    facts: dict[str, dict] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)
    lnr: list[dict] = field(default_factory=list)  # принятые упоминания ЛНР
    schema_error: str | None = None


def _quote_ok(quote: str, source_norm: str) -> str | None:
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return "цитата слишком короткая"
    if len(quote) > MAX_QUOTE:
        return "цитата слишком длинная"
    if q not in source_norm:
        return "цитаты нет в тексте документа (возможная выдумка)"
    if INJECTION.search(q):
        return "цитата похожа на указание модели (возможная prompt injection)"
    return None


def verify(raw: dict, source_text: str) -> Verified:
    out, src = Verified(), normalize(source_text)
    try:
        parsed = AiConditions.model_validate(raw)
    except ValidationError as exc:
        out.schema_error = str(exc)[:500]
        return out
    for name in TOPIC:
        fact = getattr(parsed, name)
        if fact is None:
            continue
        reason = _quote_ok(fact.quote, src)
        if reason is None and not re.search(TOPIC[name], normalize(fact.quote)):
            reason = "цитата не по теме поля"
        if reason is None and hasattr(fact.value, "strip") and name in ("term", "min_amount", "max_amount"):
            missing = _numbers(fact.value) - _numbers(fact.quote)
            if missing:
                reason = f"числа значения {sorted(missing)} отсутствуют в цитате"
        if reason:
            out.rejected.append({"field": name, "value": str(fact.value), "quote": fact.quote, "reason": reason})
        else:
            out.facts[name] = {"value": fact.value, "quote": fact.quote}
    for m in parsed.lnr_mentions:
        reason = _quote_ok(m.quote, src)
        if reason is None and not LNR_MARKER.search(normalize(m.quote)):
            reason = "в цитате нет явного упоминания ЛНР/Луганска"
        if reason is None and m.relation != "unrelated" and NOT_AVAILABILITY_CLAIM.search(normalize(m.quote)):
            reason = "цитата про контакты/уведомление, а не про доступность продукта"
        if reason:
            out.rejected.append({"field": "lnr_mentions", "value": m.relation, "quote": m.quote, "reason": reason})
        elif m.relation != "unrelated":
            out.lnr.append({"relation": m.relation, "quote": m.quote})
    return out


def lnr_status(lnr: list[dict]) -> tuple[str, str | None]:
    """confirmed — только при проверенной цитате, прямо утверждающей доступность; противоречие -> unknown."""
    avail = [m for m in lnr if m["relation"] == "product_available"]
    unavail = [m for m in lnr if m["relation"] == "product_unavailable"]
    if avail and unavail:
        return "unknown", None
    if avail:
        return "confirmed", avail[0]["quote"]
    if unavail:
        return "unavailable", unavail[0]["quote"]
    return "not_confirmed", None
