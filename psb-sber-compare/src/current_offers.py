"""Eligibility for current offers based on observations from the source."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urlsplit

from . import availability, conditions, market
from .promos import ACTIVE, EXPIRED

MOSCOW = timezone(timedelta(hours=3))
REGIONS = {"lnr": "ЛНР", "lugansk": "Луганск"}
AMOUNT = 500_000
SCENARIOS = {"Вклады": 12, "Кредиты": 36}


def source_verified(url: str, checked_at: str, now: datetime, hours: int) -> bool:
    try:
        source = urlsplit(url)
        checked = datetime.fromisoformat(checked_at)
    except (TypeError, ValueError):
        return False
    # Day-level observations cannot establish an hourly freshness window.
    if source.scheme != "https" or not source.hostname or len(checked_at) < 16:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=MOSCOW)
    return timedelta() <= now - checked <= timedelta(hours=hours)


def product_in_region(status, region: str) -> bool:
    if not status or status.code != availability.LNR or not status.source:
        return False
    # The Genbank disclosure establishes residency eligibility only.
    if status.source == availability.GENBANK_CREDIT_CARD_TERMS:
        return False
    try:
        evidence = urlsplit(status.source)
    except ValueError:
        return False
    if evidence.scheme != "https" or not evidence.hostname:
        return False
    return region == "lnr" or (region == "lugansk" and status.city_confirmed)


def current_product(product, status, region: str, now: datetime, hours: int) -> bool:
    terms = product.terms or {}
    end = terms.get("Действует до", "")
    if end:
        try:
            if date.fromisoformat(end) < now.date():
                return False
        except ValueError:
            return False
    return (product_in_region(status, region)
            and not ({"Источник условий: витрина", "Импорт из файла"} & terms.keys())
            and not terms.get(conditions.CLOSED_KEY)
            and source_verified(product.source_url, product.collected_at, now, hours))


@dataclass
class Leader:
    bank: str
    title: str
    url: str
    checked_at: str
    value: float
    region_reason: str
    region_source: str


def _scenario_metric(product, months: int) -> float | None:
    if not (product.amount_min is not None and product.amount_max is not None
            and product.amount_min <= AMOUNT <= product.amount_max
            and product.term_min_months is not None and product.term_max_months is not None
            and product.term_min_months <= months <= product.term_max_months):
        return None
    terms = product.terms or {}
    if product.rate_conditions or not conditions.is_comparable(product):
        return None
    # Exact values for a documented scenario can also be taken from a tariff
    # or a bank calculator after normalisation. Do not infer them from ranges.
    if product.category == "Кредиты":
        if market.program_of(product) != "Потребительский кредит":
            return None
        if (product.apr_min is not None and product.apr_min == product.apr_max
                and 0 < product.apr_min < 100
                and re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*%\s*(?:годовых)?\s*", product.apr_raw, re.I)
                and terms.get("Обязательные платные услуги") == "Нет"):
            return product.apr_min
        return None
    if (product.rate_min is not None and product.rate_min == product.rate_max
            and 0 < product.rate_min < 100
            and re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*%\s*(?:годовых)?\s*", product.rate_raw, re.I)
            and terms.get("Валюта", "").casefold() in {"российский рубль", "рубли", "rub"}
            and terms.get("Выплата процентов", "").casefold() in {
                "в конце срока", "в конце срока на счет вклада", "в конце срока на счёт вклада"}
            and terms.get("База начисления процентов") == "Год"
            and product.term_min_months == product.term_max_months == months):
        return AMOUNT * product.rate_min / 100
    return None


def rankings(products, statuses, banks, *, region, now, hours, key_rate, region_methods):
    result = {}
    for category, months in SCENARIOS.items():
        offers, reasons = {}, dict.fromkeys(banks, "Нет карточки по этому сценарию")
        for product in products:
            if product.category != category or product.bank not in banks:
                continue
            bank = product.bank
            status = statuses.get(id(product))
            if not current_product(product, status, region, now, hours):
                if bank not in offers:
                    if reasons[bank] == "Нет карточки по этому сценарию":
                        reasons[bank] = "Нет свежих условий с подтверждением региона"
                continue
            metric = _scenario_metric(product, months)
            check = market.assess(product, key_rate=key_rate,
                                  region_method=market.method_of(product, region_methods))
            if metric is None or check.confidence == market.LOW:
                if bank not in offers:
                    reasons[bank] = "Не подтверждены сопоставимые условия"
                continue
            candidate = Leader(bank, product.title, product.source_url, product.collected_at,
                               metric, status.reason, status.source)
            if bank not in offers or (metric > offers[bank].value if category == "Вклады"
                                      else metric < offers[bank].value):
                offers[bank] = candidate
            reasons.pop(bank, None)
        result[category] = {
            "months": months, "checked": len(offers), "total": len(banks),
            "leaders": sorted(offers.values(), key=lambda x: (
                -x.value if category == "Вклады" else x.value, x.bank, x.title))[:3],
            "excluded_banks": reasons,
        }
    return result


_DATE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
_START = re.compile(rf"\b(?:акция\s+(?:действует|проводится|начинается)|начало акции)\s*:?\s*с?\s*{_DATE}", re.I)
_PERIOD = re.compile(rf"\b(?:акция\s+(?:действует|проводится)|срок(?: действия)? акции)\s*:?\s*(?:с\s+{_DATE}\s+)?(по|до)\s+{_DATE}(\s+включительно)?", re.I)
_CONDITIONS = re.compile(r"(?:условия участия|для участия)\s*[:—–-]?\s*([^.!?\n]+)", re.I)
_ACTION = re.compile(r"\b(?:оплат|соверш|оформ|откр|пополн|подключ|зарегистрир|"
                     r"перевед|потрат|подай|подать|купите|приобрет)\w*", re.I)
_SCOPE = re.compile(r"(?:акция действует|территория(?: проведения)? акции)\s*[:—–-]?\s*(?:только\s+)?(?:на территории\s+|в\s+)?(?:г(?:ороде)?\.?\s*)?(Луганске?|ЛНР|Луганской Народной Республике)(?=[.!?\n;]|$)", re.I)
_OPEN = re.compile(r"\bакция действует (?:бессрочно|до отмены)\b", re.I)


def active_promo(promo, *, region: str, now: datetime, hours: int) -> bool:
    if promo.status == EXPIRED or not source_verified(promo.source_url, promo.checked_at, now, hours):
        return False
    text = promo.text.strip()
    scopes = {match.casefold() for match in _SCOPE.findall(text)}
    city = bool(scopes & {"луганск", "луганске"})
    if not scopes or (region == "lugansk" and not city):
        return False
    conditions_match = _CONDITIONS.search(text)
    if not conditions_match or not _ACTION.search(conditions_match[1]):
        return False
    starts = _START.search(text)
    if starts:
        try:
            day, month, year = map(int, re.split(r"[./-]", starts[1]))
            if date(year, month, day) > now.date():
                return False
        except ValueError:
            return False
    elif re.search(r"\b(?:акция начн[её]тся|акция начинается|начало акции|будет проводиться|"
                   r"акция (?:действует|проводится) с)\b", text, re.I):
        return False
    period = _PERIOD.search(text)
    if period and promo.status == ACTIVE:
        try:
            day, month, year = map(int, re.split(r"[./-]", period[3]))
            end = date(year, month, day)
        except ValueError:
            return False
        if end != promo.valid_until:
            return False
        return end > now.date() or (end == now.date() and (period[2].casefold() == "по" or bool(period[4])))
    return bool(_OPEN.search(text)) and promo.valid_until is None
