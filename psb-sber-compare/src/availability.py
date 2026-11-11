"""Есть ли продукт в Луганске — главный вопрос ТЗ.

У каждого продукта — один из четырёх статусов и основание для него:

* «есть в ЛНР, условия ЛНР» — регион ЛНР выбран на сайте или в калькуляторе
  банка, либо банк работает только в ЛНР (ЦМР);
* «есть в ЛНР, условия общероссийские» — банк в ЛНР работает (источник в
  настройке presence_source), а отдельных условий для ЛНР на сайте нет:
  по ТЗ тогда берутся общероссийские;
* «нет в ЛНР» — есть прямое указание: калькулятор пишет «недоступно в
  вашем регионе», на странице сказано «не предоставляется в … ЛНР» и т. п.;
* «не установлено» — ни того, ни другого; что проверено, сказано в
  основании. Такие продукты — первые кандидаты на доработку сбора.

Статус не додумывается: каждое основание — это ссылка, цитата или
настройка с источником.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from . import card_terms, conditions, market

LNR, FEDERAL, ABSENT, UNKNOWN = "lnr", "federal", "absent", "unknown"

LABELS = {
    LNR: "есть в ЛНР, условия ЛНР",
    FEDERAL: "общероссийские условия; доступность в ЛНР не подтверждена",
    ABSENT: "нет в ЛНР",
    UNKNOWN: "не установлено",
}
ICONS = {LNR: "🟢", FEDERAL: "🔵", ABSENT: "🔴", UNKNOWN: "⚪"}
#: Какой статус сильнее, когда у банка несколько продуктов одной программы.
RANK = {LNR: 3, FEDERAL: 2, UNKNOWN: 1, ABSENT: 0}

_REGION_WORDS = (r"(?:ЛНР|Луганск\w*|"
                 r"нов\w+\s+(?:регион|субъект|территори)\w*)")
# «Не предоставляется в ДНР, ЛНР…», «недоступна для жителей новых регионов»,
# «кроме Луганской Народной Республики». Только в одном предложении с
# названием региона — общее «не выдаётся» без региона ничего не доказывает.
_CLAUSE = re.compile(
    r"[^.!?\n]{0,120}?(?:\bне\s+(?:предоставля|выда[её]т|выдаю|оформля|обслужива|"
    r"распространя|действу)\w*|недоступ\w*|\bкроме\b|\bза\s+исключением\b)"
    r"[^.!?\n]{0,100}?" + _REGION_WORDS + r"[^.!?\n]{0,60}", re.I)
# Наоборот — программа именно для новых регионов: это не оговорка.
_FOR_REGION = re.compile(r"\bдля\s+(?:жителей\s+)?" + _REGION_WORDS, re.I)


def find_clause(text: str) -> str:
    """Цитата со страницы: продукт в ЛНР/новых регионах не предоставляется."""
    for match in _CLAUSE.finditer(text or ""):
        quote = " ".join(match.group(0).split())
        if _FOR_REGION.search(quote) and not re.search(r"\bне\b|недоступ", quote, re.I):
            continue
        return quote[:220]
    return ""


@dataclass
class Status:
    code: str
    reason: str          # основание: что именно показало
    source: str = ""     # ссылка или настройка

    @property
    def label(self) -> str:
        return LABELS[self.code]

    @property
    def icon(self) -> str:
        return ICONS[self.code]


def status_of(product: Any, *, region_method: str, presence: str = "") -> Status:
    """Статус наличия продукта в ЛНР и основание.

    region_method — как условия банка привязаны к ЛНР (market.method_of):
    selector — регион выбран на сайте, local — банк работает только в ЛНР,
    federal — про ЛНР на сайте ничего нет, not_confirmed — не выбран.
    presence — источник, что банк в ЛНР работает (banks.<код>.presence_source).
    """
    terms = getattr(product, "terms", None) or {}
    url = getattr(product, "source_url", "") or ""
    absent = terms.get(market.REGION_KEY)
    if absent:
        return Status(ABSENT, str(absent), url)
    calc = str(terms.get("Калькулятор на сайте") or "")
    # «Есть в ЛНР» — только если калькулятор для ЛНР показал хоть одну ставку:
    # строка из одних «недоступно» и «не показал расчёт» этого не доказывает.
    if (calc and "регион не выбран" not in calc and re.search(r"луганск", calc, re.I)
            and re.search(r"\d\s?%", calc)):
        return Status(LNR, f"калькулятор на сайте банка: {calc}", url)
    if region_method == "selector":
        return Status(LNR, "условия получены на сайте банка с выбранным регионом ЛНР", url)
    if region_method == "local":
        return Status(LNR, "банк работает только в ЛНР — условия на сайте луганские",
                      presence or url)
    if region_method == "federal":
        if presence:
            return Status(FEDERAL, "присутствие банка в ЛНР подтверждено; доступность этого "
                                   "продукта и способ оформления в Луганске требуют проверки", presence)
        return Status(UNKNOWN, "отдельных условий для ЛНР на сайте нет, а присутствие "
                               "банка в ЛНР не подтверждено источником", url)
    return Status(UNKNOWN, "регион на сайте банка при сборе не выбран — чьи это "
                           "условия, неизвестно", url)


def statuses(products: Iterable[Any], *, region_methods: dict[str, str],
             presence: dict[str, str]) -> dict[int, Status]:
    """Статус каждого продукта — по id объекта (продукты не хешируются)."""
    return {id(p): status_of(p, region_method=market.method_of(p, region_methods),
                             presence=presence.get(p.bank, ""))
            for p in products}


# --- таблица ТЗ: продукт Сбера × банк --------------------------------------

@dataclass
class Cell:
    status: Status | None          # None — аналога у банка не нашлось
    product: Any = None
    rate: float | None = None
    close: bool = True             # аналог по смыслу, а не просто той же программы
    note: str = ""                 # почему аналога нет


@dataclass
class Row:
    product: Any                   # продукт Сбера
    program: str
    own: Status
    cells: dict[str, Cell]


def _rate(product: Any) -> float | None:
    if product.category in market.SAVINGS:
        return product.rate_max if product.rate_max is not None else product.rate_min
    return product.rate_min if product.rate_min is not None else product.rate_max


#: Сегмент продукта по названию: с кем его честно сравнивать. «Социальный
#: вклад» ВТБ (19 %, для получателей соцвыплат) — аналог «Социального вклада»
#: Сбера, а не «Вклада Выгодный старт» (замечание 03.11.2026: все вклады Сбера
#: сравнивались с соцвкладом ВТБ, «Деньги до пенсии» — с газификацией 3 %).
_SEGMENTS = (
    ("соц", re.compile(r"социальн|соцвыплат|мер\w*\s+социальн|ветеран", re.I)),
    ("пенс", re.compile(r"пенсион|пенси[ия]", re.I)),
    # «Накопилка» — копилка для всех, не детская: «копилк» без «на» перед ним.
    ("дети", re.compile(r"детск|дет(?:ей|и)\b|ребен|ребён|kids|школ|подрост|(?<!на)копилк|юн\w+\s", re.I)),
    ("молод", re.compile(r"молод|студент|стипенд|young", re.I)),
    ("зарпл", re.compile(r"зарплат", re.I)),
    ("прем", re.compile(r"премиал|premium|сберперв|private|supreme|премьер|привилег", re.I)),
    ("валюта", re.compile(r"юан|дирхам|рупи|доллар|евро|валют", re.I)),
    # Сама валюта — суть вклада: юани сравниваем с юанями, а не с дирхамами.
    ("юань", re.compile(r"юан|cny", re.I)),
    ("дирхам", re.compile(r"дирхам|aed", re.I)),
    ("рупия", re.compile(r"рупи|inr", re.I)),
    ("доллар", re.compile(r"доллар|usd", re.I)),
    ("евро", re.compile(r"евро\b|eur\b", re.I)),
    # Ставка привязана к ключевой ЦБ и меняется вслед за ней — другой
    # механизм, чем фиксированная ставка: «Вклад Ключевой» ↔ «ВТБ-Вклад
    # «Ключевой»», но не «Выгодный старт» (03.11.2026).
    ("ключ", re.compile(r"ключев", re.I)),
    ("путеш", re.compile(r"тревел|путешеств|аэрофлот|миль|airlines|travel|s7", re.I)),
    # «Образование» само по себе — не господдержка: «Кредит на образование»
    # ВТБ под 19,9 % — не аналог «Кредита на образование с господдержкой» под 3 %.
    ("господ", re.compile(r"господдерж|газифик|льготн|субсид", re.I)),
    ("иностр", re.compile(r"иностран|мигрант|нерезидент", re.I)),
    ("благо", re.compile(r"подари\s+жизнь|благотвор", re.I)),
    # «Автонакопления», «автоплатёж» — сервисы, а не автомобиль.
    ("авто", re.compile(r"\bавто(?!накоп|плат|пополн|перевод)|автомоб|машин", re.I)),
    # Вклад для участников программы долгосрочных сбережений — не обычный
    # вклад: «Забота о будущем» 22 % ≠ «Выгодное начало» ВТБ (03.11.2026).
    ("пдс", re.compile(r"забота\s+о\s+будущ|программ\w*\s+долгосрочн|\bпдс\b", re.I)),
    # Сервис накоплений (автоперевод части трат или зарплаты) — не вклад.
    ("сервис", re.compile(r"автонакоп|автокопил|округлени\w*\s+покуп", re.I)),
    # Платёжный счёт без карты — не дебетовая карта.
    ("счёт", re.compile(r"^платёжн\w*\s+сч[её]т|^платежн\w*\s+сч[её]т", re.I)),
    # Пушкинская карта — культурная программа для 14–22 лет, а не обычная
    # дебетовая; рефинансирование кредиток — кредит, а не карта; земля,
    # гараж, комбинированная ипотека — отдельные продукты (03.11.2026).
    ("пушкин", re.compile(r"пушкинск", re.I)),
    ("рефин", re.compile(r"рефинанс", re.I)),
    ("земля", re.compile(r"земл|земел|участ", re.I)),
    ("гараж", re.compile(r"гараж|машино|кладов", re.I)),
    ("комб", re.compile(r"комбинир", re.I)),
    ("город", re.compile(r"петербур|москв|кузбас|жител|единая\s+карта|екп|приморец|уралочк|"
                         r"оренбурж|сахалин|самарск|мордови|вологд|псков|(?<![а-яё])тройк|ситикард", re.I)),
    ("ип", re.compile(r"\bип\b|предпринимател|самозанят", re.I)),
    ("кобренд", re.compile(r"магнит|кибер|яндекс|ozon|озон|лукойл|lamoda|ламода|ржд|цска|"
                            r"болельщ|адафа|пят[её]роч|перекр[её]ст|okko|wildberries|all\s+airlines", re.I)),
    ("стикер", re.compile(r"стикер", re.I)),
    ("пакет", re.compile(r"пакет|сберпрайм|\bпрайм|привилег", re.I)),
    ("номинал", re.compile(r"номинальн", re.I)),
    ("рассрочка", re.compile(r"оплата\s+частями|рассрочк|за\s+покупку|сплит|плати\s+частями", re.I)),
    ("ислам", re.compile(r"islam|исламск|халял", re.I)),
)

#: Продукт с узким назначением (гараж, земля, ИП, рассрочка…) без такого же
#: назначения у банка — не аналог: «Ипотека на гараж» ≠ «Выгодная ипотека».
# Строительство и готовый дом разделяет сама программа (market._PROGRAMS);
# земля — мягкий признак: «Загородная недвижимость и земля» Сбера и «Жилой
# дом с земельным участком» РостФинанса — аналоги.
_STRICT = {"гараж", "иностр", "ип", "пакет", "номинал", "рассрочка",
           "комб", "стикер", "пушкин", "рефин", "ислам", "соц", "прем", "ключ",
           "юань", "дирхам", "рупия", "доллар", "евро", "пдс", "счёт", "сервис"}
#: Узкое назначение, которое не определяет программу: такой продукт не
#: представляет программу в «Месте Сбера» (ипотека для иностранцев — не
#: «рыночная ипотека» Сбера).
NARROW = {"иностр", "ип", "гараж", "комб", "номинал", "пакет", "ислам", "пушкин", "стикер"}
#: Общий признак, который сам по себе не делает продукты аналогами: две
#: кобрендовые карты разных партнёров, две городские карты, вклады в разной валюте.
_LOOSE = {"кобренд", "город", "валюта"}


#: Основной продукт банка в категории — его берём для обычного продукта Сбера.
_FLAGSHIP = re.compile(r"^(?:дебетовая|кредитная)\s+карта(?:\s+(?:втб|мир|black|пс?б))?$|"
                       r"мультикарт|\bblack\b|platinum|платинум|карта\s+возможност|"
                       r"^кредит\s+наличными$|^ипотека\s+на\s+(?:вторичн|новостро)|"
                       r"^накопительн\w*\s+(?:\S+-)?сч[её]т$", re.I)


#: Механизм ставки из описания продукта на его же странице: «ставка меняется
#: вслед за ключевой ставкой ЦБ» — плавающая, даже если в названии этого нет.
_FLOATING = re.compile(r"вслед\s+за\s+ключев|ключев\w*\s+ставк\w*\s+(?:цб|банка\s+россии)?\s*"
                       r"(?:минус|плюс|[-−+])|привязан\w*\s+к\s+ключев|равн\w*\s+ключев", re.I)


#: Кредит на покупку в магазине — суть «оплаты частями», а не кредита
#: наличными: «Кредит с пониженной ставкой» Сбера — «оплачивайте товары и
#: услуги в кредит… в первый месяц до 3 %» (03.11.2026).
_POS_LOAN = re.compile(r"товар\w*\s+(?:и\s+услуг\w*\s+)?в\s+кредит|"
                       r"в\s+кредит\s+онлайн\s+или\s+в\s+магазин", re.I)


def segments(product: Any) -> set[str]:
    title = getattr(product, "title", "") or ""
    tags = {tag for tag, pattern in _SEGMENTS if pattern.search(title)}
    context = str((getattr(product, "terms", None) or {}).get("Контекст на странице", ""))
    if _FLOATING.search(context):
        tags.add("ключ")
    if _POS_LOAN.search(context):
        tags.add("рассрочка")
    # Заголовок не по-русски — языковая копия страницы для иностранцев.
    if title and not re.search(r"[а-яё]", title, re.I):
        tags.add("иностр")
    return tags


def similarity(own: Any, twin: Any) -> int:
    """Насколько продукт банка — аналог продукта Сбера (больше — ближе)."""
    a, b = segments(own), segments(twin)
    # Одна программа — уже частичное сходство (вклад есть вклад).
    score = 1 + 3 * len(a & b) - 2 * len(b - a) - len(a - b)
    # Узкое назначение должно совпадать с обеих сторон — иначе не аналог.
    if (a ^ b) & _STRICT:
        return -10
    # Тип ставки: тот же — ближе всего; промо-ставки (новые деньги,
    # приветственная, короткий срок) близки между собой. Нишевый продукт банка
    # — аналог только при общем сегменте: «Социальный» ↔ «Социальный», но
    # «Инвестиционный+» ВТБ (вклад с инвестпродуктом) — не аналог ни
    # «СберВклада», ни «Пенсионного плюс».
    mine = conditions.same_kind(conditions.kind_of(own)[0])
    theirs = conditions.same_kind(conditions.kind_of(twin)[0])
    promo = {conditions.WELCOME, conditions.NEW_MONEY, conditions.SHORT_TERM}
    # У карт «тип ставки» считается по условиям кешбэка — для подбора аналога
    # важно только, нишевая карта или нет.
    # Скидка за зарплату или подписку у кредита — не другой продукт.
    if getattr(own, "category", "") not in market.SAVINGS:
        mine = conditions.NICHE if mine == conditions.NICHE else conditions.BASE
        theirs = conditions.NICHE if theirs == conditions.NICHE else conditions.BASE
    if mine == theirs:
        score += 2
    elif mine in promo and theirs in promo:
        score += 1
    if theirs == conditions.NICHE and not a & b:
        score -= 3
    # Для обычного продукта Сбера — основной продукт банка, а не тематический.
    if not b and mine == theirs and _FLAGSHIP.search(getattr(twin, "title", "") or ""):
        score += 1
    if (getattr(twin, "terms", None) or {}).get(conditions.CLOSED_KEY):
        score -= 5
    return score


#: Одна программа в разных разделах сайтов: у Сбера «Кредит под залог
#: недвижимости» — в кредитах, у ВТБ и ПСБ — в ипотеке (03.11.2026).
_SAME_PROGRAM = {("Кредиты", "Кредит под залог"): ("*", "Залог недвижимости"),
                 ("Ипотека", "Кредит под залог недвижимости"): ("*", "Залог недвижимости")}


def _slot(product: Any) -> tuple[str, str]:
    key = (product.category or "", market.program_of(product))
    return _SAME_PROGRAM.get(key, key)


def is_close(own: Any, twin: Any, score: int | None = None) -> bool:
    """Прямой аналог: всё, что у продукта Сбера особенного, есть и у продукта
    банка, и сходство не только в «общих» признаках (две кобрендовые карты
    разных партнёров — не аналоги)."""
    a, b = segments(own), segments(twin)
    score = similarity(own, twin) if score is None else score
    return score >= 2 and not (a - b) and not (a and a <= _LOOSE)


def matrix(products: list[Any], *, home: str, banks: list[str],
           status: dict[int, Status]) -> list[Row]:
    """Каждый продукт Сбера и аналоги у каждого банка: та же категория и
    программа (семейная ипотека — с семейной). Из нескольких аналогов банка
    берётся самый близкий по смыслу (сегмент по названию и тип ставки), при
    равенстве — доступнее в ЛНР, затем с лучшей ставкой. Нишевые и особые
    продукты Сбера тоже в таблице: по ТЗ — все продукты."""
    by_key: dict[tuple[str, str, str], list[Any]] = {}
    for p in products:
        by_key.setdefault((p.bank, *_slot(p)), []).append(p)
    rows = []
    for own in sorted((p for p in products if p.bank == home),
                      key=lambda p: (p.category or "", market.program_of(p), p.title)):
        program = market.program_of(own)
        cells: dict[str, Cell] = {}
        for bank in banks:
            if bank == home:
                continue
            twins = by_key.get((bank, *_slot(own)), [])
            if not twins:
                cells[bank] = Cell(None)
                continue
            higher = own.category in market.SAVINGS

            def key(p: Any) -> tuple:
                r = _rate(p)
                # При равенстве — самый общий продукт банка (короче название:
                # «Дебетовая карта ВТБ», а не тематическая).
                return (similarity(own, p), RANK[status[id(p)].code], r is not None,
                        (r if higher else -r) if r is not None else 0,
                        -len(getattr(p, "title", "") or ""))
            best = max(twins, key=key)
            score = similarity(own, best)
            if score < 1:
                # Той же программы у банка только непохожие продукты («Кредит на
                # газификацию» для «Кредита с пониженной ставкой») — прямого
                # аналога нет, так и пишем, а не подставляем первый попавшийся.
                cells[bank] = Cell(None, note=f"прямого аналога нет (ближайший — «{best.title}»)")
                continue
            cells[bank] = Cell(status[id(best)], best, _rate(best), close=is_close(own, best, score))
        rows.append(Row(own, program, status[id(own)], cells))
    return rows


def completeness(products: list[Any], status: dict[int, Status], *, home: str) -> dict[str, int]:
    """Сколько продуктов Сбера в каждом статусе — проверка полноты по ТЗ."""
    out = {code: 0 for code in LABELS}
    for p in products:
        if p.bank == home:
            out[status[id(p)].code] += 1
    return out
