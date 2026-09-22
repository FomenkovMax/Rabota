"""Классификация акций: актуальность, сегмент, тип и размер выгоды.

Сырой список предложений с сайта для анализа не годится: в нём вперемешку
действующие акции, завершённые прошлогодние и статьи про ценные бумаги,
попавшие туда из-за омонима — «акция» как предложение и «акции» как
ценные бумаги. Этот модуль приводит список к виду, по которому можно
сравнивать два банка.

Каждое предложение получает:
  • сегмент — к какому продукту относится;
  • статус — действует, завершилась или срок неизвестен;
  • тип выгоды — кешбэк, ставка, рубли, баллы, приз;
  • размер выгоды — число, по которому предложения и сравниваются.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

log = logging.getLogger(__name__)

ACTIVE, EXPIRED, UNDATED = "active", "expired", "undated"

STATUS_LABEL = {
    ACTIVE: "Действует",
    EXPIRED: "Завершилась",
    UNDATED: "Бессрочная",
}

CASHBACK, RATE, MONEY, POINTS, PRIZE, DISCOUNT, FREE, OTHER = (
    "cashback", "rate", "money", "points", "prize", "discount", "free", "other"
)


# --- сегменты -------------------------------------------------------------

# Сегмент определяем по разделу сайта: он точнее текста, потому что
# «кешбэк на такси» встречается и у дебетовой, и у кредитной карты.
SEGMENT_BY_SECTION: dict[str, str] = {
    "debetcards": "Дебетовые карты",
    "creditcards": "Кредитные карты",
    "cards": "Банковские карты",
    "pensioncards": "Пенсионные карты",
    "pensioners": "Пенсионные продукты",
    "salary": "Зарплатные карты",
    "loans": "Кредиты",
    "mortgage": "Ипотека",
    "saving": "Вклады",
    "savingsaccount": "Накопительные счета",
    "insurance": "Страхование",
    "wealth": "Инвестиции",
    "premium": "Премиальное обслуживание",
    "ecommerce": "Счета и переводы",
    "pds": "Долгосрочные сбережения",
}

# Для акций, лежащих в корне /personal, раздела нет — определяем по тексту.
SEGMENT_BY_KEYWORD: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"кредитн\w*\s+карт", re.I), "Кредитные карты"),
    (re.compile(r"дебетов\w*\s+карт|карт[аоуы]\s+«?мир", re.I), "Дебетовые карты"),
    (re.compile(r"зарплатн", re.I), "Зарплатные карты"),
    (re.compile(r"пенси", re.I), "Пенсионные продукты"),
    (re.compile(r"ипотек", re.I), "Ипотека"),
    (re.compile(r"кредит", re.I), "Кредиты"),
    (re.compile(r"вклад|депозит", re.I), "Вклады"),
    (re.compile(r"накопительн", re.I), "Накопительные счета"),
    (re.compile(r"инвест|брокер|облигац", re.I), "Инвестиции"),
    (re.compile(r"страхов", re.I), "Страхование"),
]

BONUS_SEGMENT = "Кешбэк и бонусные программы"
SERVICE_SEGMENT = "Сервисы и услуги"
OTHER_SEGMENT = "Прочие предложения"

# Акции, лежащие в корне /personal, к конкретному продукту не привязаны:
# «Дополнительный кешбэк на покупки» может работать и по дебетовой карте,
# и по кредитной. Приписывать им продукт наугад нельзя — это выдумка.
# Зато их можно сгруппировать по существу предложения, и тогда они
# сравниваются со сберовскими корректно: кешбэк с кешбэком.
_SERVICE_RE = re.compile(r"консультац|юридическ|правокард|налог|госуслуг", re.I)
_CARD_TARIFF_RE = re.compile(r"тариф\w*\s+карт", re.I)


def segment_of(source_path: str, title: str, text: str = "",
               benefit_type: str = "") -> str:
    """Сегмент предложения: раздел сайта → ключевые слова → тип выгоды."""
    parts = [p for p in (source_path or "").split("/") if p]
    # ['personal', 'debetcards', 'mir-cashback'] → раздел на втором месте
    if len(parts) >= 2 and parts[0] == "personal":
        segment = SEGMENT_BY_SECTION.get(parts[1])
        if segment:
            return segment

    # Эти признаки ищем в заголовке, а не во всём тексте: заголовок
    # определяет суть предложения, а в тексте может мелькнуть партнёр.
    # «Домашний кешбэк» от компании «Правокард» — это кешбэк, а не услуга.
    head = title or ""
    if _CARD_TARIFF_RE.search(head):
        return "Банковские карты"
    if _SERVICE_RE.search(head):
        return SERVICE_SEGMENT

    blob = f"{title} {text}"

    for pattern, segment in SEGMENT_BY_KEYWORD:
        if pattern.search(blob):
            return segment

    # Продукт неизвестен, но суть предложения известна — этого достаточно,
    # чтобы поставить его в один ряд со сберовским предложением того же типа.
    if benefit_type in (CASHBACK, POINTS, DISCOUNT):
        return BONUS_SEGMENT
    if re.search(r"кешб[эе]к|кэшб[эе]к|бонус|балл|покупк", blob, re.I):
        return BONUS_SEGMENT
    return OTHER_SEGMENT


# --- отсев не-акций -------------------------------------------------------

# «Акция» — это предложение, «акции» — ценные бумаги. Из-за омонима в выборку
# попадают статьи инвестиционного раздела: «Что такое акции», «Когда растут
# цены на акции». Ловим их по вопросительно-обучающей форме заголовка.
_ARTICLE_RE = re.compile(
    r"^(что такое|как (заработать|подключить|пользоваться|выбрать|получить доступ)|"
    r"когда (растут|падают)|зачем|почему|чем отличается|инвестируйте в|"
    r"инвестиции в|во что инвестировать)",
    re.I,
)
# Объявления и инструкции, которые предложением не являются.
_NOTICE_RE = re.compile(
    r"^(мы продлили|информация|уведомлени|правила|условия обслуживания|"
    r"документы|тариф)", re.I,
)


def is_offer(title: str, text: str = "") -> bool:
    """Отличает предложение от статьи или объявления."""
    head = (title or "").strip()
    if not head:
        return False
    if _ARTICLE_RE.match(head) or _NOTICE_RE.match(head):
        return False
    return True


# --- актуальность ---------------------------------------------------------

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

_FINISHED_RE = re.compile(r"акция\s+(завершена|окончена|завершилась)|"
                          r"предложение\s+(завершено|окончено)", re.I)

# Дата в тексте — ещё не срок акции. «Для владельцев карт, полученных
# до 31 января 2024» описывает условие участия, а не окончание: приняв это
# за срок, можно объявить завершённой действующую акцию.
# Поэтому дату засчитываем, только если рядом стоит слово про срок.
_EXPIRY_CONTEXT_RE = re.compile(
    r"(акци\w*|предложени\w*|действу\w*|действительн\w*|срок\w*|"
    r"продлен\w*|продлится|"
    # Призыв к действию с дедлайном — это тоже срок акции:
    # «откройте счёт до 31 января», «оформите карту до 31 декабря».
    r"успейте|оформите|откройте|подключите|активируйте|станьте|"
    r"получите|соверши\w*|купите|переведите)", re.I
)
# Причастия, после которых дата почти всегда описывает условие участия.
_QUALIFIER_RE = re.compile(
    r"(полученн\w*|оформленн\w*|выпущенн\w*|открыт\w*|заключённ\w*|"
    r"заключенн\w*|соверш[её]нн\w*|выданн\w*|зарегистрированн\w*)\s*$",
    re.I,
)

# «по 31 марта 2024», «до 31.12.2026», «до 31 октября»
_DATE_TEXT_RE = re.compile(
    r"(?:по|до|включительно по)\s+(\d{1,2})\s+([а-я]+)\s*(\d{4})?", re.I
)
_DATE_NUM_RE = re.compile(r"(?:по|до)\s+(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", re.I)
# Дата сразу после «акция завершена», без предлога.
_FINISHED_DATE_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})")


def _is_expiry_context(text: str, match_start: int) -> bool:
    """Проверяет, что дата относится к сроку акции, а не к условию участия."""
    window = text[max(0, match_start - 60):match_start]
    if _QUALIFIER_RE.search(window):
        return False
    return bool(_EXPIRY_CONTEXT_RE.search(window))


def _month_from_word(word: str) -> int | None:
    lowered = word.lower()
    for stem, number in _MONTHS.items():
        if lowered.startswith(stem):
            return number
    return None


def parse_valid_until(text: str) -> tuple[date | None, bool]:
    """Дата окончания предложения и признак «год указан явно».

    Год важен: «до 31 октября» без года трактовать нельзя — можно случайно
    похоронить действующую акцию или воскресить прошлогоднюю.
    """
    for match in _DATE_NUM_RE.finditer(text):
        if not _is_expiry_context(text, match.start()):
            continue
        day, month, year = (int(g) for g in match.groups())
        if year < 100:
            year += 2000
        try:
            return date(year, month, day), True
        except ValueError:
            continue

    for match in _DATE_TEXT_RE.finditer(text):
        if not _is_expiry_context(text, match.start()):
            continue
        day_raw, month_word, year_raw = match.groups()
        month = _month_from_word(month_word)
        if month is None:
            continue
        try:
            if year_raw:
                return date(int(year_raw), month, int(day_raw)), True
            return date(date.today().year, month, int(day_raw)), False
        except ValueError:
            continue

    return None, False


def status_of(title: str, text: str, today: date | None = None) -> tuple[str, date | None]:
    """Статус предложения и дата окончания, если её удалось определить."""
    today = today or date.today()
    blob = f"{title} {text}"

    finished = _FINISHED_RE.search(blob)
    if finished:
        until, _ = parse_valid_until(blob)
        if until is None:
            # «Акция завершена 30.06.2026» — дата стоит без предлога.
            tail = _FINISHED_DATE_RE.search(blob[finished.end():finished.end() + 40])
            if tail:
                day, month, year = (int(g) for g in tail.groups())
                if year < 100:
                    year += 2000
                try:
                    until = date(year, month, day)
                except ValueError:
                    until = None
        return EXPIRED, until

    until, year_known = parse_valid_until(blob)
    if until is None:
        return UNDATED, None

    if not year_known:
        # Год не указан — судить о завершении нельзя, не отсеиваем.
        return UNDATED, None

    return (EXPIRED if until < today else ACTIVE), until


# --- выгода ---------------------------------------------------------------


BENEFIT_LABEL = {
    CASHBACK: "Кешбэк",
    RATE: "Ставка",
    MONEY: "Рублями",
    POINTS: "Баллы",
    PRIZE: "Розыгрыш",
    DISCOUNT: "Скидка",
    FREE: "Бесплатно",
    OTHER: "Прочее",
}

def format_benefit(value: float, unit: str) -> str:
    """Размер выгоды с правильной единицей измерения."""
    if unit == "₽":
        return f"{value:,.0f}".replace(",", " ") + " ₽"
    if unit == "баллов":
        return f"{value:,.0f}".replace(",", " ") + " баллов"
    if unit == "%":
        return f"{value:g}".replace(".", ",") + " %"
    return f"{value:g}".replace(".", ",")

_PERCENT_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_RUB_RE = re.compile(r"(\d[\d\s ]*)\s*(?:₽|руб)", re.I)
_POINTS_RE = re.compile(r"(\d[\d\s ]*)\s*балл", re.I)


def _first_number(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


PCT, RUB, PTS, NONE_UNIT = "%", "₽", "баллов", ""


def parse_benefit(title: str, text: str = "") -> tuple[str, float | None, str]:
    """Тип выгоды, её размер и единица измерения.

    Единицу возвращаем отдельно, а не выводим из типа: кешбэк бывает и
    в процентах, и в рублях («кешбэк 9000 ₽»), и жёсткая привязка единицы
    к типу превращала такую сумму в «9000 %».

    Порядок проверок неслучаен: «снизим ставку до 5% при кредите от 1 млн ₽»
    — это про ставку, а не про рубли, хотя рубли в строке есть.
    """
    blob = f"{title} {text}"

    if re.search(r"ставк", blob, re.I):
        return RATE, _first_number(_PERCENT_RE, blob), PCT
    if re.search(r"кешб[эе]к|кэшб[эе]к|верн[её]м|вернем|возврат", blob, re.I):
        percent = _first_number(_PERCENT_RE, blob)
        if percent is not None:
            return CASHBACK, percent, PCT
        return CASHBACK, _first_number(_RUB_RE, blob), RUB
    if re.search(r"балл", blob, re.I):
        return POINTS, _first_number(_POINTS_RE, blob), PTS
    if re.search(r"розыгрыш|выиграй|приз|лотере", blob, re.I):
        return PRIZE, _first_number(_RUB_RE, blob), RUB
    if re.search(r"скидк", blob, re.I):
        percent = _first_number(_PERCENT_RE, blob)
        if percent is not None:
            return DISCOUNT, percent, PCT
        return DISCOUNT, _first_number(_RUB_RE, blob), RUB
    if re.search(r"бесплатн|без комиссии|0\s*₽", blob, re.I):
        return FREE, None, NONE_UNIT

    rub = _first_number(_RUB_RE, blob)
    if rub is not None:
        return MONEY, rub, RUB
    percent = _first_number(_PERCENT_RE, blob)
    if percent is not None:
        return OTHER, percent, PCT
    return OTHER, None, NONE_UNIT


# --- модель ---------------------------------------------------------------

@dataclass
class PromoInsight:
    """Предложение, приведённое к сравнимому виду."""

    bank: str
    title: str
    text: str = ""
    url: str = ""
    source_path: str = ""

    segment: str = OTHER_SEGMENT
    status: str = UNDATED
    valid_until: date | None = None
    benefit_type: str = OTHER
    benefit_value: float | None = None
    benefit_unit: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABEL[self.status]

    @property
    def benefit_label(self) -> str:
        return BENEFIT_LABEL[self.benefit_type]

    @property
    def benefit_display(self) -> str:
        if self.benefit_value is None:
            return BENEFIT_LABEL[self.benefit_type]
        return format_benefit(self.benefit_value, self.benefit_unit)

    @property
    def is_guaranteed(self) -> bool:
        """Розыгрыш — не гарантированная выгода, сравнивать её нельзя."""
        return self.benefit_type != PRIZE

    @property
    def valid_display(self) -> str:
        if self.valid_until:
            return self.valid_until.strftime("%d.%m.%Y")
        return "срок не указан"


def classify(bank: str, title: str, text: str, url: str, source_path: str,
             *, today: date | None = None, segment: str = "") -> PromoInsight | None:
    """Приводит предложение к сравнимому виду. None — если это не акция."""
    if not is_offer(title, text):
        return None

    status, until = status_of(title, text, today=today)
    benefit_type, benefit_value, benefit_unit = parse_benefit(title, text)

    return PromoInsight(
        bank=bank, title=title, text=text, url=url, source_path=source_path,
        segment=segment or segment_of(source_path, title, text, benefit_type),
        status=status, valid_until=until,
        benefit_type=benefit_type, benefit_value=benefit_value,
        benefit_unit=benefit_unit,
    )


def classify_all(rows: Iterable[Any], bank: str, *, today: date | None = None,
                 segment_hint: str = "") -> list[PromoInsight]:
    """Классифицирует пачку строк из базы или объектов Promo."""
    out: list[PromoInsight] = []
    for row in rows:
        if hasattr(row, "keys"):
            title = row["title"] or ""
            text = row["text"] or ""
            url = row["url"] or ""
            path = row["source_path"] or ""
            hint = (row["category"] or "") if "category" in row.keys() else ""
        else:
            title = getattr(row, "title", "")
            text = getattr(row, "text", "")
            url = getattr(row, "url", "")
            path = getattr(row, "source_path", "")
            hint = ""
        insight = classify(bank, title, text, url, path,
                           today=today, segment=segment_hint or hint)
        if insight is not None:
            out.append(insight)
    return out


# --- сравнение по сегментам ----------------------------------------------

@dataclass
class SegmentComparison:
    """Итог по одному сегменту: чьи акции сильнее."""

    segment: str
    psb: list[PromoInsight] = field(default_factory=list)
    sber: list[PromoInsight] = field(default_factory=list)

    verdict: str = ""          # green | yellow | red | grey
    headline: str = ""         # короткий вывод
    best_type: str = ""        # по какому типу выгоды сравнивали
    best_unit: str = ""        # и в каких единицах
    psb_best: float | None = None
    sber_best: float | None = None

    @property
    def total(self) -> int:
        return len(self.psb) + len(self.sber)


def _best_by(promos: list[PromoInsight], benefit_type: str, unit: str) -> float | None:
    """Максимум выгоды одного типа И одной единицы измерения.

    Единица обязательна: «кешбэк 30%» и «кешбэк 9000 ₽» — величины разной
    природы, и максимум по их объединению не значит ничего.
    """
    values = [p.benefit_value for p in promos
              if p.benefit_type == benefit_type and p.benefit_unit == unit
              and p.benefit_value is not None and p.is_guaranteed]
    return max(values) if values else None


# Чем сравнивать предложения между собой, в порядке предпочтения.
# Проценты идут первыми: «кешбэк 30%» — понятная мера выгоды, а «2000
# баллов» зависит от курса балла и прямо с процентом не сопоставляется.
HEADLINE_PRIORITY: tuple[tuple[str, str], ...] = (
    (CASHBACK, PCT), (RATE, PCT), (DISCOUNT, PCT),
    (CASHBACK, RUB), (MONEY, RUB), (DISCOUNT, RUB), (POINTS, PTS),
)


def best_offer(promos: list["PromoInsight"],
               benefit_type: str = "", unit: str = "") -> "PromoInsight | None":
    """Сильнейшее предложение банка в сегменте.

    Выбирать максимум по голому числу нельзя: «2000 баллов» обошло бы
    «кешбэк 30%» просто потому, что 2000 больше 30. Поэтому сначала
    фиксируем тип выгоды и единицу, а максимум ищем уже внутри них.
    """
    if not promos:
        return None

    order = ([(benefit_type, unit)] if benefit_type else []) + list(HEADLINE_PRIORITY)
    for want_type, want_unit in order:
        group = [p for p in promos
                 if p.benefit_type == want_type and p.benefit_unit == want_unit
                 and p.benefit_value is not None and p.is_guaranteed]
        if group:
            return max(group, key=lambda p: p.benefit_value)

    # Ничего измеримого — отдаём первое гарантированное предложение.
    guaranteed = [p for p in promos if p.is_guaranteed]
    return (guaranteed or promos)[0]


def sort_key(promo: PromoInsight) -> tuple[int, float, str]:
    """Порядок показа: гарантированная выгода выше розыгрышей.

    Иначе «розыгрыш 1 000 000 ₽» встаёт первым в сегменте и выглядит
    весомее реального кешбэка 30%, хотя достаётся одному человеку.
    """
    return (0 if promo.is_guaranteed else 1,
            -(promo.benefit_value or 0), promo.title)


def compare_segments(psb: list[PromoInsight], sber: list[PromoInsight]) -> list[SegmentComparison]:
    """Группирует акции по сегментам и выносит вердикт по каждому.

    Сравниваем внутри одного типа выгоды: кешбэк с кешбэком, ставку со
    ставкой. Сопоставлять «30% кешбэка» с «5000 ₽ бонуса» бессмысленно —
    это разные величины, и такой вердикт вводил бы в заблуждение.
    """
    segments = sorted({p.segment for p in psb} | {p.segment for p in sber})
    results: list[SegmentComparison] = []

    for segment in segments:
        item = SegmentComparison(
            segment=segment,
            psb=[p for p in psb if p.segment == segment],
            sber=[p for p in sber if p.segment == segment],
        )
        _judge(item)
        results.append(item)

    # Сначала те, где проигрываем, — руководителю важно именно это.
    order = {"red": 0, "yellow": 1, "green": 2, "grey": 3}
    results.sort(key=lambda s: (order.get(s.verdict, 4), -s.total, s.segment))
    return results


def _judge(item: SegmentComparison) -> None:
    if not item.sber:
        item.verdict = "red" if item.psb else "grey"
        item.headline = (f"У ПСБ {len(item.psb)} предложений, у Сбера нет ни одного"
                         if item.psb else "Предложений нет ни у одного банка")
        return
    if not item.psb:
        item.verdict = "green"
        item.headline = f"У Сбера {len(item.sber)} предложений, у ПСБ нет ни одного"
        return

    # Ищем выгоду, сопоставимую по типу И по единице измерения.
    candidates = [
        (benefit_type, unit)
        for benefit_type in (CASHBACK, RATE, MONEY, POINTS, DISCOUNT)
        for unit in (PCT, RUB, PTS)
        if _best_by(item.psb, benefit_type, unit) is not None
        and _best_by(item.sber, benefit_type, unit) is not None
    ]

    if not candidates:
        item.verdict = "grey"
        item.headline = (f"ПСБ {len(item.psb)}, Сбер {len(item.sber)} — "
                         "выгода несопоставима по типу или единице измерения")
        return

    benefit_type, unit = candidates[0]
    psb_best = _best_by(item.psb, benefit_type, unit)
    sber_best = _best_by(item.sber, benefit_type, unit)

    item.best_type, item.best_unit = benefit_type, unit
    item.psb_best, item.sber_best = psb_best, sber_best
    label = BENEFIT_LABEL[benefit_type].lower()

    # По ставке кредита выгода клиента — меньше; по кешбэку и деньгам — больше.
    lower_is_better = benefit_type == RATE and item.segment not in (
        "Вклады", "Накопительные счета", "Долгосрочные сбережения")
    sber_wins = (sber_best < psb_best) if lower_is_better else (sber_best > psb_best)

    psb_text = format_benefit(psb_best, unit)
    sber_text = format_benefit(sber_best, unit)

    if psb_best == sber_best:
        item.verdict = "yellow"
        item.headline = f"Максимальный {label} одинаковый — {psb_text}"
    elif sber_wins:
        item.verdict = "green"
        item.headline = f"Максимальный {label}: Сбер {sber_text} против {psb_text} у ПСБ"
    else:
        item.verdict = "red"
        item.headline = f"Максимальный {label}: ПСБ {psb_text} против {sber_text} у Сбера"


def summarize_promos(promos: list[PromoInsight]) -> dict[str, int]:
    counts = {ACTIVE: 0, EXPIRED: 0, UNDATED: 0}
    for promo in promos:
        counts[promo.status] += 1
    return counts
