"""Позиция Сбера на рынке ЛНР и качество данных.

Светофор сравнивает только пары, подтверждённые вручную. Этот модуль
отвечает на другой вопрос — где Сбер среди всех банков сразу:

  • продукты раскладываются по блокам (DEP, LOAN, MTG…) и программам
    внутри блока: семейную ипотеку сравниваем с семейной, а не с рыночной;
  • по каждой программе у каждого банка берётся лучшая витринная ставка;
  • считается место Сбера, лучший банк, медиана остальных и статус:
    лидер | в рынке | отстаёт | не найдено у Сбера | нет у конкурентов.

Прежде чем цифра попадёт в сравнение, она проходит проверки правдоподобия
(ключевая ставка ЦБ, ПСК против ставки, регион). Подозрительные значения
остаются в данных с низкой достоверностью, но в рейтинг не идут: одна
неверная цифра в отчёте у руководителя подрывает доверие ко всему.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse

from . import conditions

# --- справочники ----------------------------------------------------------

#: Код банка для product_id и BI. Новый банк — новая строка.
BANK_CODE = {
    "Сбер": "SBER", "ПСБ": "PSB", "ВТБ": "VTB", "Т-Банк": "TBANK",
    "ЦМР": "CMR", "РостФинанс": "ROSTFIN",
}

#: Категория продукта → продуктовый блок спецификации.
BLOCK_OF = {
    "Вклады": "DEP", "Накопительные счета": "DEP",
    "Дебетовые карты": "CARD", "Кредитные карты": "CARD",
    "Банковские карты": "CARD", "Пенсионные карты": "CARD",
    "Кредиты": "LOAN", "Автокредиты": "LOAN",
    "Ипотека": "MTG",
    "Счета и переводы": "DAILY",
    "Долгосрочные сбережения": "INV", "Инвестиционные услуги": "INV",
    "Страхование": "INV",
    "Специальные предложения": "SEG", "Акции и спецпредложения": "SEG",
}

BLOCK_LABEL = {
    "DEP": "Сбережения", "CARD": "Карты", "LOAN": "Кредиты", "MTG": "Ипотека",
    "DAILY": "Повседневный банкинг", "CHANNEL": "Каналы", "INV": "Инвестиции и страхование",
    "SEG": "Сегментные предложения", "OTHER": "Прочее",
}

#: Сберегательные категории: клиенту выгоднее ставка выше.
SAVINGS = {"Вклады", "Накопительные счета"}

#: Категории, где процент на странице — это ставка. У дебетовых карт,
#: страховки и акций проценты другие (кешбэк, % на остаток, доля
#: возврата), и проверять их как ставку нельзя.
CREDIT = {"Кредиты", "Автокредиты", "Ипотека", "Кредитные карты"}
RATED = SAVINGS | CREDIT

#: Программы внутри категории. Порядок важен: первое совпадение побеждает,
#: поэтому «Семейная военная ипотека» уходит в военную, а не в семейную.
_PROGRAMS: dict[str, tuple[tuple[str, str], ...]] = {
    "Ипотека": (
        (r"(?<!без )залог", "Кредит под залог недвижимости"),
        (r"военн", "Военная ипотека"),
        (r"рефинанс", "Рефинансирование ипотеки"),
        (r"семейн", "Семейная ипотека"),
        (r"нов\w+\s+(регион|субъект|территор)|днр|лнр", "Льготная для новых регионов"),
        (r"дальневост|арктич", "Дальневосточная и арктическая"),
        (r"\bит\b|\bit\b|айти", "IT-ипотека"),
        (r"самол[её]т|застройщ|партн[её]р", "С застройщиком-партнёром"),
        (r"сельск", "Сельская ипотека"),
        (r"ижс|строительств|загородн|\bдом\b", "ИЖС и загородные дома"),
        (r"материнск", "С материнским капиталом"),
        (r"вторичн|готов", "Вторичное жильё"),
        (r"новостро|строящ", "Новостройки"),
    ),
    "Кредиты": (
        (r"рефинанс", "Рефинансирование"),
        (r"(?<!без )залог", "Кредит под залог"),
        (r"\bавто", "Автокредит"),
        (r"образова", "Образовательный кредит"),
    ),
}
_DEFAULT_PROGRAM = {"Ипотека": "Рыночная ипотека", "Кредиты": "Потребительский кредит"}

#: Программы с господдержкой или субсидией — им ставка ниже ключевой простительна.
_SUBSIDISED = re.compile(
    r"льготн|семейн|госпрограм|господдерж|нов\w+\s+(регион|субъект|территор)|"
    r"дальневост|арктич|\bит\b|\bit\b|военн|субсид|сельск|образова", re.I)

#: Страница раздела, принятая за продукт: «Вклады … для физических лиц».
_SECTION_PAGE = re.compile(r"для\s+(физических|частных)\s+лиц", re.I)

#: Вместо названия — кусок адреса страницы: название не распозналось.
_SLUG_TITLE = re.compile(r"^[a-z0-9_\-]+$")

#: На сколько ПСК может быть ниже ставки без вопросов, п.п. Минимумы
#: «ставка от» и «ПСК от» на витрине бывают посчитаны для разных сроков
#: и сумм, поэтому сотые доли расхождения ошибкой не считаем.
PSK_TOLERANCE_PP = 0.5

#: Насколько ставка вклада может превышать ключевую без вопросов, п.п.
DEPOSIT_OVER_KEY_PP = 3.0

HIGH, MEDIUM, LOW = "high", "medium", "low"
CONFIDENCE_LABEL = {HIGH: "высокая", MEDIUM: "средняя", LOW: "низкая"}

LEADER, IN_MARKET, BEHIND = "лидер", "в рынке", "отстаёт"
# «Не найдено», а не «нет»: сбор мог не дойти до страницы программы, и
# утверждать, что у Сбера её нет вовсе, по одному обходу сайта нельзя.
NO_SBER, NO_RIVALS, NO_DATA = "не найдено у Сбера", "нет у конкурентов", "нет данных"


def method_of(product: Any, region_methods: dict[str, str]) -> str:
    """Способ привязки к региону: записанный при сборе, иначе — по банку.

    Исключение — «регион не выбран» при сборе, когда в настройках банку
    с тех пор задан local или federal. Сайт отдал те же страницы, просто
    теперь известно, как их понимать (ЦМР работает только в ЛНР), и
    ждать ради этого нового сбора незачем. Обратное не действует: если
    регион при сборе был выбран, это факт, и настройки его не отменяют.
    """
    stored = getattr(product, "region_method", "") or ""
    configured = region_methods.get(product.bank, "")
    if stored in ("", "not_confirmed") and configured in ("local", "federal"):
        return configured
    return stored or configured or "selector"


def bank_code(bank: str) -> str:
    return BANK_CODE.get(bank) or _slug(bank).upper() or "BANK"


def block_of(product: Any) -> str:
    return BLOCK_OF.get(product.category or "", "OTHER")


def program_of(product: Any) -> str:
    """Программа внутри категории — то, что честно сравнивать между собой."""
    category = product.category or "Прочее"
    title = (product.title or "").lower()
    for pattern, program in _PROGRAMS.get(category, ()):
        if re.search(pattern, title, re.I):
            return program
    return _DEFAULT_PROGRAM.get(category, category)


def better_of(category: str) -> str:
    """Что выгоднее клиенту по ставке: higher или lower."""
    return "higher" if category in SAVINGS else "lower"


# --- product_id -----------------------------------------------------------

_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n",
     "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y",
     "", "e", "yu", "ya"]))


def _slug(text: str, limit: int = 40) -> str:
    low = (text or "").lower()
    out = "".join(_TRANSLIT.get(ch, ch) for ch in low)
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out[:limit].strip("-")


_WEAK_SEGMENTS = {"", "index", "main", "online", "new", "person", "personal", "ru"}


def product_ids(products: Iterable[Any]) -> dict[int, str]:
    """product_id для каждого продукта: {BANK}-{блок}-{короткое имя}.

    Имя берётся из адреса страницы, а не из названия: адрес переживает
    переименование продукта, и история по нему не рвётся. Если адреса нет
    или он общий у нескольких продуктов, берётся название.
    Ключ словаря — id(product).
    """
    items = list(products)
    stems: dict[int, list[str]] = {}
    for product in items:
        key = str(getattr(product, "product_key", "") or product.url_path or "")
        parsed = urlparse(key)
        parts = [p for p in parsed.path.split("/") if p]
        candidates = []
        if parsed.fragment:
            candidates.append(_slug(parsed.fragment))
        for depth in (1, 2, 3):
            if len(parts) >= depth and parts[-1].lower() not in _WEAK_SEGMENTS:
                candidates.append(_slug("-".join(parts[-depth:])))
        candidates.append(_slug(product.title))
        stems[id(product)] = [c for c in candidates if c] or ["product"]

    # Берём самое короткое имя, которое уникально внутри банка и блока.
    out: dict[int, str] = {}
    groups: dict[tuple[str, str], list[Any]] = {}
    for product in items:
        groups.setdefault((product.bank, block_of(product)), []).append(product)
    for (bank, block), group in groups.items():
        taken: set[str] = set()
        for level in range(4):
            pending = [p for p in group if id(p) not in out]
            if not pending:
                break
            names: dict[str, list[Any]] = {}
            for p in pending:
                options = stems[id(p)]
                names.setdefault(options[min(level, len(options) - 1)], []).append(p)
            for name, owners in names.items():
                if len(owners) == 1 and name not in taken:
                    out[id(owners[0])] = name
                    taken.add(name)
        for p in group:
            if id(p) not in out:
                base = stems[id(p)][-1]
                name, n = base, 2
                while name in taken:
                    name, n = f"{base}-{n}", n + 1
                out[id(p)] = name
                taken.add(name)
        for p in group:
            out[id(p)] = f"{bank_code(bank)}-{block}-{out[id(p)]}"
    return out


# --- достоверность --------------------------------------------------------

@dataclass
class Assessment:
    confidence: str = HIGH
    issues: list[str] = field(default_factory=list)
    has_rate: bool = True

    def lower(self, level: str, issue: str) -> None:
        order = {HIGH: 0, MEDIUM: 1, LOW: 2}
        if order[level] > order[self.confidence]:
            self.confidence = level
        self.issues.append(issue)

    @property
    def usable(self) -> bool:
        """Можно ли ставку продукта ставить в рейтинг и выводы."""
        return self.has_rate and self.confidence != LOW


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(",.").replace(".", ",")


def assess(product: Any, *, key_rate: float | None, region_method: str) -> Assessment:
    """Проверки правдоподобия по правилам спецификации."""
    result = Assessment()
    terms = getattr(product, "terms", None) or {}
    category = product.category or ""
    title = product.title or ""
    rate_low, rate_high = product.rate_min, product.rate_max

    rated = category in RATED

    if rated and rate_low is None and rate_high is None:
        result.has_rate = False
        result.issues.append("ставка на странице не указана")
    if not rated:
        result.has_rate = False

    if region_method == "not_confirmed":
        result.lower(LOW, "регион на сайте не выбран — условия не ЛНР")

    if _SECTION_PAGE.search(title) or title.strip().lower() == category.lower():
        result.lower(LOW, "похоже на страницу раздела, а не на продукт")
    elif _SLUG_TITLE.match(title.strip()):
        result.lower(MEDIUM, "название продукта не распознано — вместо него адрес страницы")

    if rated and terms.get("Источник ставки"):
        result.lower(MEDIUM, "ставка взята с карточки на витрине, а не со страницы продукта")

    if result.has_rate:
        values = [v for v in (rate_low, rate_high) if v is not None]
        if any(v <= 0 or v >= 100 for v in values):
            result.lower(LOW, "ставка вне разумного диапазона")

        if key_rate is not None and category in SAVINGS:
            top = max(values)
            if top > key_rate + DEPOSIT_OVER_KEY_PP:
                result.lower(LOW, f"ставка {_fmt(top)} % выше ключевой ЦБ "
                                  f"({_fmt(key_rate)} %) больше чем на "
                                  f"{_fmt(DEPOSIT_OVER_KEY_PP)} п.п. — перепроверить: "
                                  "промо, особые условия или ошибка разбора")

        if key_rate is not None and category in CREDIT and not _SUBSIDISED.search(title):
            low = min(values)
            if low < key_rate:
                result.lower(LOW, f"кредит дешевле ключевой ЦБ ({_fmt(low)} % < "
                                  f"{_fmt(key_rate)} %) без госпрограммы — перепроверить: "
                                  "субсидия партнёра, промо или ошибка разбора")

        # У кредитных карт ПСК законно бывает ниже ставки: её считают
        # с учётом льготного периода. Поэтому проверка — только для кредитов.
        apr = product.apr_min
        if (apr is not None and rate_low is not None and category != "Кредитные карты"
                and apr < rate_low - PSK_TOLERANCE_PP):
            result.lower(LOW, f"ПСК {_fmt(apr)} % ниже номинальной ставки "
                              f"{_fmt(rate_low)} % — так не бывает, ошибка разбора")

    return result


# --- позиция Сбера --------------------------------------------------------

@dataclass
class Offer:
    bank: str
    value: float
    title: str
    url: str


@dataclass
class Gap:
    """Строка анализа: одна программа, все банки."""

    block: str
    program: str
    metric: str                     # rate_max | rate_min
    better: str                     # higher | lower
    sber: Offer | None = None
    best: Offer | None = None
    others_median: float | None = None
    delta_vs_best: float | None = None     # Сбер − лучший, п.п.
    delta_vs_median: float | None = None   # Сбер − медиана остальных, п.п.
    rank: int | None = None
    banks_compared: int = 0
    status: str = NO_DATA
    comment: str = ""
    offers: list[Offer] = field(default_factory=list)
    category: str = ""

    @property
    def place(self) -> str:
        if self.rank is None:
            return "—"
        return f"{self.rank} из {self.banks_compared}"

    @property
    def advantage(self) -> float | None:
        """Насколько Сбер лучше медианы остальных для клиента, п.п."""
        if self.delta_vs_median is None:
            return None
        return self.delta_vs_median if self.better == "higher" else -self.delta_vs_median


def build_gaps(products: Iterable[Any], *, home: str, key_rate: float | None,
               region_methods: dict[str, str], parity_pp: float = 0.5) -> list[Gap]:
    """Место Сбера по каждой программе, где ставка что-то значит.

    В расчёт идут только продукты с пригодной ставкой: регион подтверждён,
    проверки правдоподобия пройдены. Остальные видны в разделе качества.
    """
    groups: dict[tuple[str, str], list[Any]] = {}
    for product in products:
        category = product.category or ""
        if category not in RATED:
            continue
        groups.setdefault((category, program_of(product)), []).append(product)

    gaps: list[Gap] = []
    for (category, program), items in groups.items():
        better = better_of(category)
        metric = "rate_max" if better == "higher" else "rate_min"
        gap = Gap(block=BLOCK_OF.get(category, "OTHER"), program=program,
                  metric=metric, better=better, category=category)

        best_by_bank: dict[str, Offer] = {}
        sber_listed = False
        skipped_home = 0
        special_home = 0
        for product in items:
            if product.bank == home:
                sber_listed = True
            # Только базовые ставки: приветственные, премиальные, зарплатные
            # и нишевые — в блоке «Специальные условия» (аудит 07.10.2026).
            if not conditions.is_comparable(product):
                if product.bank == home:
                    special_home += 1
                continue
            method = method_of(product, region_methods)
            check = assess(product, key_rate=key_rate, region_method=method)
            value = _value(product, metric)
            if value is None or not check.usable:
                if product.bank == home:
                    skipped_home += 1
                continue
            offer = Offer(product.bank, value, product.title, product.source_url or "")
            current = best_by_bank.get(product.bank)
            if current is None or _better(value, current.value, better):
                best_by_bank[product.bank] = offer

        offers = sorted(best_by_bank.values(), key=lambda o: o.value,
                        reverse=(better == "higher"))
        gap.offers = offers
        gap.banks_compared = len(offers)
        gap.sber = best_by_bank.get(home)
        others = [o for o in offers if o.bank != home]
        if offers:
            gap.best = offers[0]
        if others:
            gap.others_median = round(statistics.median(o.value for o in others), 3)

        if gap.sber is None:
            if not sber_listed:
                gap.status = NO_SBER if others else NO_DATA
                gap.comment = ("сбор не нашёл программу на сайте Сбера — "
                               "проверить вручную, есть ли она" if others else "")
            elif special_home and not skipped_home:
                gap.status = NO_DATA
                gap.comment = ("у Сбера здесь только ставки на особых условиях "
                               "(приветственные, премиальные, нишевые) — "
                               "см. «Специальные условия»")
            else:
                gap.status = NO_DATA
                gap.comment = ("у Сбера продукт есть, но ставка не прошла проверку "
                               "или не найдена на странице — см. «Качество данных»")
            gaps.append(gap)
            continue

        sber = gap.sber.value
        gap.rank = 1 + sum(1 for o in offers if _better(o.value, sber, better))
        gap.delta_vs_best = round(sber - gap.best.value, 3) if gap.best else None
        if gap.others_median is not None:
            gap.delta_vs_median = round(sber - gap.others_median, 3)

        if not others:
            gap.status = NO_RIVALS
            gap.comment = "у конкурентов нет сопоставимой программы с проверенной ставкой"
        elif gap.rank == 1:
            gap.status = LEADER
        elif gap.advantage is not None and gap.advantage >= -parity_pp:
            gap.status = IN_MARKET
        else:
            gap.status = BEHIND
        gaps.append(gap)

    order = {BEHIND: 0, NO_SBER: 1, IN_MARKET: 2, LEADER: 3, NO_RIVALS: 4, NO_DATA: 5}
    block_order = ["DEP", "LOAN", "MTG", "CARD"]
    gaps.sort(key=lambda g: (block_order.index(g.block) if g.block in block_order else 9,
                             order.get(g.status, 9), g.program))
    return gaps


def _value(product: Any, metric: str) -> float | None:
    value = getattr(product, metric)
    if value is None:
        value = product.rate_min if metric == "rate_max" else product.rate_max
    return value


def _better(a: float, b: float, better: str) -> bool:
    return a > b if better == "higher" else a < b


# --- качество данных ------------------------------------------------------

@dataclass
class QualityRow:
    bank: str
    block: str
    products: int = 0
    rated: int = 0          # продукты, у которых ставка — ключевой параметр
    with_rate: int = 0
    usable: int = 0
    not_confirmed: int = 0
    low: int = 0
    issues: dict[str, int] = field(default_factory=dict)

    @property
    def coverage_pct(self) -> float | None:
        """Доля продуктов с проверенной ставкой. None — у блока ставок нет."""
        return round(100.0 * self.usable / self.rated, 1) if self.rated else None


_ISSUE_KIND = (
    ("регион", "регион не выбран"),
    ("страницу раздела", "страница раздела вместо продукта"),
    ("витрин", "ставка с витрины"),
    ("выше ключевой", "вклад выше ключевой +3 п.п."),
    ("дешевле ключевой", "кредит дешевле ключевой"),
    ("ПСК", "ПСК ниже ставки"),
    ("не указана", "ставка не найдена на странице"),
    ("не распознано", "название не распознано"),
    ("вне разумного", "ставка вне диапазона"),
)


def issue_kind(issue: str) -> str:
    for marker, label in _ISSUE_KIND:
        if marker in issue:
            return label
    return issue


def quality(products: Iterable[Any], *, key_rate: float | None,
            region_methods: dict[str, str]) -> tuple[list[QualityRow], list[tuple[Any, Assessment]]]:
    """Покрытие по банкам и блокам плюс список «Нужна ручная проверка».

    Покрытие — доля продуктов, у которых есть ставка, прошедшая проверки.
    В ручную проверку попадают продукты с подозрительной ставкой; продукты
    без ставки туда не идут — их видно по покрытию, и это не ошибка, а
    честное «на странице не указано».
    """
    rows: dict[tuple[str, str], QualityRow] = {}
    manual: list[tuple[Any, Assessment]] = []
    for product in products:
        block = block_of(product)
        row = rows.setdefault((product.bank, block), QualityRow(product.bank, block))
        method = method_of(product, region_methods)
        check = assess(product, key_rate=key_rate, region_method=method)
        row.products += 1
        row.rated += int((product.category or "") in RATED)
        row.with_rate += int(check.has_rate)
        row.usable += int(check.usable)
        row.not_confirmed += int(method == "not_confirmed")
        row.low += int(check.confidence == LOW)
        for issue in check.issues:
            kind = issue_kind(issue)
            row.issues[kind] = row.issues.get(kind, 0) + 1
        if check.has_rate and check.confidence == LOW and method != "not_confirmed":
            manual.append((product, check))
    ordered = sorted(rows.values(), key=lambda r: (r.bank, r.block))
    manual.sort(key=lambda item: (item[0].bank, item[0].category or "", item[0].title))
    return ordered, manual


@dataclass
class SpecialRow:
    """Ставка на особых условиях — показывается отдельно от рейтинга."""

    bank: str
    category: str
    program: str
    title: str
    rate: float | None
    kind: str
    kind_label: str
    reason: str
    url: str


def specials(products: Iterable[Any], *, key_rate: float | None,
             region_methods: dict[str, str]) -> list[SpecialRow]:
    """Продукты со ставкой на особых условиях: в «Место Сбера» они не идут."""
    rows = []
    for product in products:
        category = product.category or ""
        if category not in RATED:
            continue
        kind, reason = conditions.kind_of(product)
        if kind == conditions.BASE:
            continue
        metric = "rate_max" if better_of(category) == "higher" else "rate_min"
        rows.append(SpecialRow(
            bank=product.bank, category=category, program=program_of(product),
            title=product.title, rate=_value(product, metric), kind=kind,
            kind_label=conditions.LABELS[kind], reason=reason,
            url=product.source_url or ""))
    order = {kind: i for i, kind in enumerate(conditions.LABELS)}
    rows.sort(key=lambda r: (r.category, order.get(r.kind, 99), r.bank, r.title))
    return rows
