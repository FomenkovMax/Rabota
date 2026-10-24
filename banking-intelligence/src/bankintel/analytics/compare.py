"""Сравнение вкладов в одинаковых клиентских сценариях.

Ставка на сайте — диапазон («от 12% до 14,1%», «до 14%»), фактическая зависит от срока, суммы и
условий, которых сайт не раскрывает однозначно. Поэтому результат — ИНТЕРВАЛ дохода:
максимум по верхней границе ставки и минимум по нижней (если она указана).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bankintel.analytics.calc import simple_interest
from bankintel.analytics.facts import ProductFacts
from bankintel.analytics.parsing import months_to_days

STALE_AFTER = timedelta(days=7)


@dataclass(frozen=True)
class Scenario:
    amount: Decimal
    months: int
    currency: str = "RUB"

    def __post_init__(self):
        if self.amount <= 0 or self.months <= 0:
            raise ValueError("Сумма и срок должны быть положительными")

    @property
    def days(self) -> int:
        return months_to_days(self.months)


DEFAULT_SCENARIOS = (
    Scenario(Decimal(100_000), 3),
    Scenario(Decimal(100_000), 6),
    Scenario(Decimal(100_000), 12),
    Scenario(Decimal(500_000), 12),
    Scenario(Decimal(1_000_000), 12),
)


@dataclass
class ScenarioResult:
    facts: ProductFacts
    eligible: bool
    exclusion: str | None = None
    warnings: list[str] = field(default_factory=list)
    income_min: Decimal | None = None
    income_max: Decimal | None = None


def evaluate(facts: ProductFacts, sc: Scenario, now: datetime | None = None) -> ScenarioResult:
    def excluded(reason: str) -> ScenarioResult:
        return ScenarioResult(facts, False, exclusion=reason)

    if facts.category != "deposit":
        return excluded("не вклад (счета сравниваются по ставкам, без расчёта дохода)")
    if facts.currency is None:
        return excluded("валюта продукта не определена")
    if facts.currency != sc.currency:
        return excluded(f"валюта {facts.currency}, сценарий в {sc.currency}")
    if facts.rate_max is None:
        return excluded("ставка не распознана")
    if facts.term is None:
        return excluded(f"срок «{facts.term_text or 'не указан'}» не распознан")
    if not facts.term.allows(sc.days):
        return excluded(f"срок {sc.months} мес. не подходит под «{facts.term_text}»")

    warnings: list[str] = []
    if facts.amount is None:
        warnings.append("ограничения по сумме не распознаны")
    else:
        if facts.amount.min is not None and sc.amount < facts.amount.min:
            return excluded(f"сумма меньше минимальной ({facts.amount.min:,.0f})".replace(",", " "))
        if facts.amount.max is not None and sc.amount > facts.amount.max:
            return excluded(f"сумма больше максимальной ({facts.amount.max:,.0f})".replace(",", " "))

    income_max = simple_interest(sc.amount, facts.rate_max, sc.days)
    income_min = simple_interest(sc.amount, facts.rate_min, sc.days) if facts.rate_min is not None else None
    if facts.rate_min is None:
        warnings.append("нижняя граница ставки на сайте не указана — известна только верхняя")
    elif facts.rate_min != facts.rate_max:
        warnings.append("фактическая ставка зависит от срока, суммы и условий (сайт даёт диапазон)")
    if "floating_rate" in facts.flags:
        warnings.append("плавающая ставка (привязана к ключевой ставке ЦБ)")
    if "limited_time" in facts.flags:
        warnings.append("предложение ограничено по времени (см. описание на сайте)")
    if "restricted_audience" in facts.flags:
        warnings.append("предложение для ограниченной категории клиентов или с особыми условиями")
    if facts.lnr_status != "confirmed":
        warnings.append("доступность в ЛНР не подтверждена источником")
    now = now or datetime.now(UTC)
    if facts.checked_at is not None:
        checked = facts.checked_at if facts.checked_at.tzinfo else facts.checked_at.replace(tzinfo=UTC)
        if now - checked > STALE_AFTER:
            warnings.append(f"данные старше 7 дней (от {checked:%d.%m.%Y})")
    else:
        warnings.append("дата проверки неизвестна")
    return ScenarioResult(facts, True, None, warnings, income_min, income_max)


@dataclass
class ComparisonReport:
    scenario: Scenario
    results: list[ScenarioResult]
    banks_without_data: list[str]

    @property
    def eligible(self) -> list[ScenarioResult]:
        return sorted((r for r in self.results if r.eligible), key=lambda r: r.income_max, reverse=True)

    @property
    def excluded(self) -> list[ScenarioResult]:
        return [r for r in self.results if not r.eligible]

    @property
    def eligible_open(self) -> list[ScenarioResult]:
        """Предложения без ограничений по категории клиентов и обязательных условий."""
        return [r for r in self.eligible if "restricted_audience" not in r.facts.flags]

    @property
    def eligible_restricted(self) -> list[ScenarioResult]:
        return [r for r in self.eligible if "restricted_audience" in r.facts.flags]

    def best_by_bank(self, *, restricted: bool = False) -> dict[str, ScenarioResult]:
        best: dict[str, ScenarioResult] = {}
        for r in (self.eligible_restricted if restricted else self.eligible_open):  # по убыванию дохода
            best.setdefault(r.facts.bank_slug, r)
        return best


def compare(
    facts: list[ProductFacts], sc: Scenario, *, all_banks: list[tuple[str, str]] = (), now: datetime | None = None
) -> ComparisonReport:
    """all_banks: [(slug, name)] всех банков реестра — для явного указания банков без данных (напр. Сбер)."""
    results = [evaluate(f, sc, now) for f in facts if f.category == "deposit"]
    with_data = {f.bank_slug for f in facts if f.category == "deposit"}
    missing = [name for slug, name in all_banks if slug not in with_data]
    return ComparisonReport(sc, results, missing)
