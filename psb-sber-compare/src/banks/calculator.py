"""Калькулятор на странице банка: регион ЛНР, все цели из списка, ставка.

Описание продукта на сайте — федеральное. Что доступно именно в Луганске,
видно только в калькуляторе: у Сбера на «Квартира на вторичном рынке» для
«Луганская Народная Республика, Луганск» он пишет «Программа недоступна в
вашем регионе» (ручная проверка 28.10.2026). Здесь то же делает агент:

1. находит поле региона, вводит «Луганск» и выбирает вариант с полным
   названием региона;
2. выключает скидки, которые калькулятор включает сам («Получаю зарплату
   на Сбер −1 %»): нужна базовая ставка, а не зарплатная;
3. открывает выпадающий список цели или программы и по очереди выбирает
   каждый пункт; после выбора читает панель результата — ставку и
   предупреждение о недоступности.

Вёрстка у банков разная, поэтому поля ищутся по подписи рядом, а не по
классам. Что найдено и что нажато — сохраняется вместе со страницей:
по этим файлам разбор дорабатывается без ручных проверок.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

# Подписи сверяются целиком (с двоеточием или «*» в конце): у Т-Банка
# 28.10.2026 «Партнёрская программа» из подвала сошла за список цели, у
# Сбера — «Программа для семей с детьми» из карточки.
# «Регион», «Регион покупки недвижимости», «Выберите регион», «Город» — с
# начала строки и коротко: в сборе 28.10.2026 строгий список упустил поле
# ВТБ (в прошлом сборе регион там выбирался).
REGION_LABEL = (r"^(?:выберите\s+|ваш\s+)?(?:регион|город)(?:\s+[а-яё]+){0,3}\s*[:*]?$")
GOAL_LABEL = (r"^(?:цель(?:\s+(?:кредита|ипотеки|кредитования))?|программа|тип\s+недвижимости|"
              r"тип\s+жилья|что\s+(?:покупаете|хотите\s+купить)|вид\s+кредита|"
              r"объект\s+недвижимости)\s*[:*]?$")
DISCOUNT_LABEL = r"зарплат|пенси|перевед[уё] зарплат"
#: Вложенный список после цели: «Квартира в новостройке» → «Программа:
#: Региональная / Семейная / Стандартная» (калькулятор Сбера, 28.10.2026).
PROGRAM_LABEL = (r"^(?:программа|программа\s+кредитования|госпрограмма|вид\s+программы|"
                 r"ипотечная\s+программа)\s*[:*]?$")
UNAVAILABLE = re.compile(r"недоступн\w*\s+в\s+(?:вашем|этом|выбранном)\s+регион|"
                         r"не\s+выда[её]тся\s+в\s+(?:вашем|этом)\s+регион", re.I)
_RATE = re.compile(
    r"(?:процентная\s+)?ставк[аи][^\d\n%]{0,40}\n?\s*(?:от\s*|до\s*)?"
    r"(\d{1,2}(?:[,.]\d{1,3})?)\s?%", re.I)
_PAYMENT = re.compile(r"(?:ежемесячный\s+)?плат[её]ж[^\d\n]{0,30}\n?\s*([\d\s ]{3,})\s?₽", re.I)

# Помечает поле с подписью: ближайший к подписи input, combobox или
# кликабельный блок. Возвращает, что нашлось.
_MARK_FIELD_JS = """
([label, mark]) => {
  const re = new RegExp(label, 'i');
  const visible = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  // Подпись бывает только в placeholder или aria-label самого поля.
  for (const field of document.querySelectorAll('input, [role=combobox]')) {
    const hint = (field.getAttribute('placeholder') || field.getAttribute('aria-label') || '').trim();
    if (hint && hint.length <= 60 && re.test(hint) && visible(field)
        && (!field.dataset.agent || field.dataset.agent === mark)
        && !field.closest('header, footer, nav')) {
      field.setAttribute('data-agent', mark);
      return {tag: field.tagName, value: field.value || field.innerText || '', label: hint};
    }
  }
  const labels = Array.from(document.querySelectorAll('body *')).filter(el => {
    const t = (el.textContent || '').trim();
    return t.length > 0 && t.length <= 60 && re.test(t) && el.children.length === 0 && visible(el)
      && !el.closest('a, nav, header, footer, [role=navigation], [class*=footer], [class*=Footer], [class*=menu]');
  });
  for (const lab of labels) {
    let box = lab;
    for (let i = 0; i < 4 && box; i++, box = box.parentElement) {
      const field = box.querySelector(
        'input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, ' +
        '[role=combobox], [aria-haspopup=listbox], [aria-haspopup=true]');
      // Поле, уже занятое другим списком (цель против программы), — не наше.
      if (field && visible(field) && (!field.dataset.agent || field.dataset.agent === mark)) {
        field.setAttribute('data-agent', mark);
        return {tag: field.tagName, value: field.value || field.innerText || '',
                label: lab.textContent.trim()};
      }
    }
    // Поля нет — кликабельный блок вокруг подписи (кастомный селект).
    const block = lab.closest('[role=button], button, [tabindex], label') || lab.parentElement;
    if (block && visible(block) && (!block.dataset.agent || block.dataset.agent === mark)) {
      block.setAttribute('data-agent', mark);
      return {tag: block.tagName, value: block.innerText || '', label: lab.textContent.trim()};
    }
  }
  return null;
}
"""

# Видимые пункты открытого списка: role=option или li во всплывающем списке.
_OPTIONS_JS = """
() => {
  const visible = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  let items = Array.from(document.querySelectorAll('[role=option]')).filter(visible);
  if (!items.length) items = Array.from(document.querySelectorAll(
    '[role=listbox] li, ul[role] li, [class*=option], [class*=Option], [class*=dropdown] li, ' +
    '[class*=Dropdown] li, [class*=menu] li')).filter(visible);
  const seen = new Set(), out = [];
  for (const el of items) {
    const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
    if (t && t.length <= 90 && !seen.has(t)) { seen.add(t); out.push(t); }
  }
  return out.slice(0, 20);
}
"""

# Выключает включённые по умолчанию скидки с подписью про зарплату/пенсию.
_DISCOUNTS_OFF_JS = """
(label) => {
  const re = new RegExp(label, 'i'), off = [];
  const toggles = document.querySelectorAll(
    'input[type=checkbox], [role=switch], [role=checkbox]');
  for (const t of toggles) {
    const on = t.checked === true || t.getAttribute('aria-checked') === 'true';
    if (!on) continue;
    let box = t, text = '';
    for (let i = 0; i < 5 && box; i++, box = box.parentElement) {
      text = (box.innerText || '').trim();
      if (text && text.length < 160) break;
    }
    if (!re.test(text)) continue;
    const target = t.tagName === 'INPUT' ? (t.closest('label') || t.parentElement || t) : t;
    try { target.click(); off.push(text.replace(/\\s+/g, ' ').slice(0, 80)); } catch (e) {}
  }
  return off;
}
"""

# Текст калькулятора: поднимаемся от поля, пока в блоке не появится
# результат (ставка с % или предупреждение), но не выше разумного размера.
_RESULT_JS = """
(mark) => {
  // Результат калькулятора — ближайшая к полю видимая цифра с «%», у которой
  // в подписи (до 300 символов вокруг) есть «ставк». Подниматься от поля до
  // общего блока нельзя: у ВТБ (28.10.2026) предки поля сразу содержат пол-
  // страницы, и первая «ставка … %» оказывалась из шапки, а не из расчёта.
  const field = document.querySelector('[data-agent="' + mark + '"]');
  if (!field) return '';
  const visible = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const f = field.getBoundingClientRect(), fx = f.left + f.width / 2, fy = f.top + f.height / 2;
  let best = '', dist = 1e9;
  // Текстовые узлы, а не элементы: цифра бывает голым текстом рядом с <br>.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const t = (node.textContent || '').trim();
    const el = node.parentElement;
    if (!t || t.length > 40 || !/\\d\\s?%/.test(t) || !el || !visible(el)) continue;
    let box = el, ctx = '';
    for (let i = 0; i < 5 && box; i++, box = box.parentElement) {
      const c = (box.innerText || '').trim();
      if (c.length > 300) break;
      ctx = c;
      if (/ставк/i.test(c)) break;
    }
    if (!/ставк/i.test(ctx)) continue;
    const r = el.getBoundingClientRect();
    const d = Math.hypot(r.left + r.width / 2 - fx, r.top + r.height / 2 - fy);
    if (d < dist) { dist = d; best = ctx; }
  }
  // Предупреждение о регионе ищем по всей странице: другой такой фразы там нет.
  const body = document.body.innerText || '';
  const warn = body.match(/[^\\n]{0,60}недоступн[^\\n]{0,80}регион[^\\n]{0,40}/i);
  return (warn ? warn[0] + '\\n' : '') + best;
}
"""


class FrameView:
    """Страница глазами калькулятора: разметка — из фрейма, клавиатура и
    ожидание — у страницы. Калькулятор Сбера может быть во встроенном окне."""

    def __init__(self, page: Any, frame: Any) -> None:
        self._page, self._frame = page, frame
        self.keyboard = page.keyboard

    def evaluate(self, script: str, arg: Any = None) -> Any:
        return self._frame.evaluate(script, arg)

    def locator(self, selector: str, **kwargs: Any) -> Any:
        return self._frame.locator(selector, **kwargs)

    def wait_for_timeout(self, ms: float) -> None:
        self._page.wait_for_timeout(ms)


def _rate(text: str) -> float | None:
    match = _RATE.search(text or "")
    return float(match.group(1).replace(",", ".")) if match else None


def read_result(text: str) -> dict[str, Any]:
    """Ставка, платёж и доступность из текста панели калькулятора."""
    payment = _PAYMENT.search(text or "")
    blocked = UNAVAILABLE.search(text or "")
    return {
        "available": not blocked,
        "rate": None if blocked else _rate(text),
        "payment": int(re.sub(r"\D", "", payment.group(1))) if payment else None,
        "note": blocked.group(0) if blocked else "",
    }


def _pick_option(page: Any, text: str) -> bool:
    for selector in ("[role=option]", "li", "[class*=option]", "div", "span"):
        loc = page.locator(selector, has_text=text)
        try:
            count = min(loc.count(), 6)
        except Exception:                           # noqa: BLE001
            continue
        for i in range(count):
            item = loc.nth(i)
            try:
                if item.is_visible() and (item.inner_text() or "").strip() == text:
                    item.click(timeout=3000)
                    return True
            except Exception:                       # noqa: BLE001
                continue
    return False


def set_region(page: Any, region: str) -> str:
    """Выбирает регион в калькуляторе. Возвращает, что стоит в поле после."""
    found = page.evaluate(_MARK_FIELD_JS, [REGION_LABEL, "region"])
    if not found:
        return ""
    head = region.split(",")[0].strip()
    if head.lower() in (found.get("value") or "").lower():
        return found["value"]
    field = page.locator('[data-agent="region"]').first
    try:
        field.click(timeout=3000)
        if found.get("tag") == "INPUT":
            field.fill("")
            field.type(region.split(",")[-1].strip() or head, delay=60)
        page.wait_for_timeout(1500)
        options = page.evaluate(_OPTIONS_JS) or []
        choice = next((o for o in options if head.lower() in o.lower()), None) or next(
            (o for o in options if "луганск" in o.lower()), None)
        if not choice or not _pick_option(page, choice):
            page.keyboard.press("Escape")
            return ""
        page.wait_for_timeout(2000)
        again = page.evaluate(_MARK_FIELD_JS, [REGION_LABEL, "region"]) or {}
        return again.get("value") or choice
    except Exception as exc:                        # noqa: BLE001
        log.debug("Регион в калькуляторе не выбран: %s", exc)
        return ""


# Видимые короткие тексты «листьев» страницы: что появилось после клика по
# полю — то и пункты списка, как бы он ни был свёрстан (Домклик у Сбера,
# 30.10.2026: ни role=option, ни li — классы с хешами).
_VISIBLE_TEXTS_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (/^(SCRIPT|STYLE|SVG|PATH|INPUT|TEXTAREA)$/i.test(el.tagName)) continue;
    if (Array.from(el.children).some(c => (c.innerText || '').trim())) continue;
    const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
    if (!t || t.length > 90) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') out.push(t);
  }
  return out;
}
"""

# Стрелка или контейнер выпадающего списка рядом с полем.
_OPEN_ARROW_JS = """
(mark) => {
  const f = document.querySelector('[data-agent="' + mark + '"]');
  let box = f;
  for (let i = 0; i < 4 && box; i++, box = box.parentElement) {
    const arrow = box.querySelector('[data-e2e-id*=arrow i], [class*=arrow i], [class*=chevron i], ' +
                                    '[class*=Arrow], button, [role=button]');
    if (arrow && arrow !== f) { arrow.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      arrow.click(); return true; }
  }
  return false;
}
"""

_NOT_OPTION = re.compile(r"^(?:\d[\d\s ]*(?:₽|%|лет|год|мес)?|рассчитать|подробнее|оформить|"
                         r"выбор значения.*)$", re.I)


def _opened_options(page: Any, before: set[str]) -> list[str]:
    options = page.evaluate(_OPTIONS_JS) or []
    if options:
        return options
    fresh = [t for t in dict.fromkeys(page.evaluate(_VISIBLE_TEXTS_JS) or [])
             if t not in before and not _NOT_OPTION.match(t)]
    # Один новый текст — подсказка, а не список.
    return fresh if len(fresh) >= 2 else []


def _list_options(page: Any, mark: str, max_options: int) -> list[str]:
    """Пункты выпадающего списка: кликом по полю, по стрелке, клавишей — или
    из <select>."""
    field = page.locator(f'[data-agent="{mark}"]').first
    options: list[str] = []
    try:
        before = set(page.evaluate(_VISIBLE_TEXTS_JS) or [])
        attempts = (lambda: field.click(timeout=3000),
                    lambda: page.evaluate(_OPEN_ARROW_JS, mark),
                    lambda: (field.focus(), page.keyboard.press("ArrowDown")))
        for attempt in attempts:
            try:
                attempt()
            except Exception as exc:                # noqa: BLE001
                log.debug("Список %s: попытка открыть не удалась: %s", mark, exc)
                continue
            page.wait_for_timeout(900)
            options = _opened_options(page, before)[:max_options]
            if options:
                break
        page.keyboard.press("Escape")
    except Exception as exc:                        # noqa: BLE001
        log.debug("Список %s не открылся: %s", mark, exc)
    if not options:
        options = page.evaluate(
            "(m) => { const s = document.querySelector('[data-agent=\"' + m + '\"]');"
            " return s && s.tagName === 'SELECT' ? Array.from(s.options).map(o => o.text.trim())"
            " : []; }", mark) or []
    return options[:max_options]


def _choose(page: Any, mark: str, option: str) -> bool:
    field = page.locator(f'[data-agent="{mark}"]').first
    tag = page.evaluate(
        "(m) => document.querySelector('[data-agent=\"' + m + '\"]')?.tagName", mark)
    if tag == "SELECT":
        field.select_option(label=option)
        return True
    for opener in (lambda: field.click(timeout=3000),
                   lambda: page.evaluate(_OPEN_ARROW_JS, mark),
                   lambda: (field.focus(), page.keyboard.press("ArrowDown"))):
        try:
            opener()
        except Exception:                           # noqa: BLE001
            continue
        page.wait_for_timeout(700)
        if _pick_option(page, option):
            return True
    page.keyboard.press("Escape")
    return False


def _read(page: Any, mark: str) -> dict[str, Any]:
    page.wait_for_timeout(2500)
    # Смена пункта может вернуть скидку по умолчанию — выключаем снова.
    if page.evaluate(_DISCOUNTS_OFF_JS, DISCOUNT_LABEL):
        page.wait_for_timeout(1500)
    text = page.evaluate(_RESULT_JS, mark) or ""
    return {**read_result(text), "text": text[:700]}


SUM_LABEL = (r"^(?:сумма(?:\s+кредита)?|сколько\s+вам\s+нужно|стоимость(?:\s+[а-яё]+){0,2}|"
             r"осталось\s+выплатить)\s*[:*]?$")
TERM_LABEL = r"^(?:срок(?:\s+кредита|\s+рефинансирования)?|на\s+срок)\s*[:*]?$"

_FIELD_VALUE_JS = """
(mark) => {
  const f = document.querySelector('[data-agent="' + mark + '"]');
  if (!f) return '';
  let box = f;
  for (let i = 0; i < 3 && box.parentElement; i++) box = box.parentElement;
  return (f.value || '') + '\\n' + (box.innerText || '').slice(0, 200);
}
"""


# Блок калькулятора с платежом: поднимаемся от поля суммы, пока в тексте
# не появится «платёж … ₽».
_PAYMENT_BLOCK_JS = """
(mark) => {
  let box = document.querySelector('[data-agent="' + mark + '"]');
  for (let i = 0; i < 10 && box; i++, box = box.parentElement) {
    const t = box.innerText || '';
    if (t.length > 4000) break;
    if (/плат[её]ж[\\s\\S]{0,80}₽/i.test(t)) return t;
  }
  return '';
}
"""
_PAYMENTS = re.compile(r"плат[её]ж[^\n]{0,40}\n?\s*(\d[\d\s  ]{2,})\s?₽", re.I)


_FIELD_HTML_JS = """
(mark) => {
  let box = document.querySelector('[data-agent="' + mark + '"]');
  for (let i = 0; i < 3 && box && box.parentElement; i++) box = box.parentElement;
  return box ? box.outerHTML.slice(0, 6000) : '';
}
"""


def _money(text: str) -> int | None:
    match = re.search(r"(\d[\d\s ]{3,})", text or "")
    return int(re.sub(r"\D", "", match.group(1))) if match else None


def _months(text: str) -> int | None:
    years = re.search(r"(\d{1,2})\s*(?:год|года|лет)", text or "", re.I)
    months = re.search(r"(\d{1,3})\s*мес", text or "", re.I)
    total = (int(years.group(1)) * 12 if years else 0) + (int(months.group(1)) if months else 0)
    if total:
        return total
    plain = re.search(r"^\s*(\d{1,3})\s*$", (text or "").split("\n")[0])
    return int(plain.group(1)) if plain else None


def implied_rate(amount: float, months: int, payment: float) -> float | None:
    """Годовая ставка по аннуитетному платежу: обратный расчёт (бисекция).

    Банк в калькуляторе показывает платёж, а ставку не пишет (автокредит
    Сбера, 28.10.2026). Это его же расчёт — ставку можно восстановить, но
    помечаем как выведенную."""
    if not amount or not months or not payment or payment * months <= amount:
        return None
    low, high = 0.0001, 2.0
    for _ in range(80):
        mid = (low + high) / 2
        r = mid / 12
        calc = amount * r / (1 - (1 + r) ** -months)
        low, high = (mid, high) if calc < payment else (low, mid)
    rate = round((low + high) / 2 * 100, 2)
    # Упёрлись в верхнюю границу поиска — платёж с суммой не сходится.
    return None if rate >= 199 else rate


_MAX_IMPLIED = 80.0


def _field_number(page: Any, mark: str, parse: Any) -> Any:
    """Число из значения поля; нет значения — из подписи вокруг поля."""
    raw = page.evaluate(_FIELD_VALUE_JS, mark) or ""
    value, _, around = raw.partition("\n")
    return parse(value) if value.strip() and parse(value) else parse(around)


def _plain_calculator(page: Any) -> dict[str, Any] | None:
    """Калькулятор без региона и цели: сумма, срок → платёж, ставка."""
    if not page.evaluate(_MARK_FIELD_JS, [SUM_LABEL, "sum"]):
        return None
    page.evaluate(_DISCOUNTS_OFF_JS, DISCOUNT_LABEL)
    result = _read(page, "sum")
    amount = _field_number(page, "sum", _money)
    term = None
    if page.evaluate(_MARK_FIELD_JS, [TERM_LABEL, "term"]):
        term = _field_number(page, "term", _months)
    block = page.evaluate(_PAYMENT_BLOCK_JS, "sum") or ""
    # Платежей бывает два: «в первый месяц» и «со 2-го месяца» — аннуитет второй,
    # он и больше (первый месяц короче).
    payments = [int(re.sub(r"\D", "", m.group(1))) for m in _PAYMENTS.finditer(block)]
    payment = result.get("payment") or (max(payments) if payments else None)
    if result.get("rate") is None:
        result["rate"] = _rate(block)
    out = {"option": "", **result, "payment": payment, "amount": amount, "term_months": term}
    if result.get("rate") is None and amount and term and payment:
        implied = implied_rate(amount, term, payment)
        # Сумма или срок прочитаны не те (подпись ползунка «от 35 000 ₽»,
        # сбор 30.10.2026 — «≈200 %»): неправдоподобную ставку не выводим.
        if implied is not None and 1 <= implied <= _MAX_IMPLIED:
            out["rate_implied"] = implied
        else:
            out["implied_rejected"] = (f"платёж {payment} за {amount} на {term} мес "
                                       f"даёт неправдоподобную ставку — не используется")
    return {"region": "", "goal_label": "", "discounts_off": [], "options": [out],
            "complete": True, "kind": "сумма и срок"}


def explore(page: Any, region: str, *, max_options: int = 12,
            budget_s: float = 120, seen: set | None = None) -> dict[str, Any] | None:
    """Регион → скидки выключены → каждый пункт списка цели (и вложенного
    списка программы, если он появляется) → результат.

    None — калькулятора с выбором цели на странице нет. Время ограничено
    budget_s: не успели — возвращаем то, что прочитали, а не теряем всё.
    """
    deadline = time.monotonic() + budget_s
    goal = page.evaluate(_MARK_FIELD_JS, [GOAL_LABEL, "goal"])
    region_field = page.evaluate(_MARK_FIELD_JS, [REGION_LABEL, "region"])
    if not goal and not region_field:
        return _plain_calculator(page)
    out: dict[str, Any] = {"region": "", "goal_label": (goal or {}).get("label", ""),
                           "discounts_off": [], "options": [], "complete": True}
    if region_field:
        out["region"] = set_region(page, region)
    out["discounts_off"] = page.evaluate(_DISCOUNTS_OFF_JS, DISCOUNT_LABEL) or []
    if out["discounts_off"]:
        page.wait_for_timeout(1500)
    if not goal:
        out["options"].append({"option": "", **_read(page, "region")})
        return out

    options = _list_options(page, "goal", max_options)
    if not options:
        # Список не открылся — сохраняем вёрстку вокруг поля (для разбора) и
        # читаем результат для цели, которая стоит по умолчанию: у Сбера
        # калькулятор на странице программы открыт на её цели, так что ставка
        # в регионе по программе всё равно будет.
        out["goal_html"] = page.evaluate(_FIELD_HTML_JS, "goal") or ""
        current = page.evaluate(
            "(m) => { const f = document.querySelector('[data-agent=\"' + m + '\"]');"
            " return f ? (f.value || f.innerText || '').trim() : ''; }", "goal") or ""
        out["options"].append({"option": f"{current} (по умолчанию)" if current else "",
                               **_read(page, "goal")})
        return out
    # Калькулятор ипотеки у банка один на все страницы программ: тот же
    # список целей уже перебран в этом сборе — второй раз не перебираем.
    key = (out["region"], tuple(options))
    if seen is not None and options:
        if key in seen:
            out["skipped"] = "тот же калькулятор уже прочитан на другой странице"
            return out
        seen.add(key)
    for option in options:
        if time.monotonic() > deadline:
            out["complete"] = False
            break
        try:
            if not _choose(page, "goal", option):
                continue
            out["options"].append({"option": option, **_read(page, "goal")})
            # Вложенный список программы — ищем заново после каждой цели:
            # у новостройки он есть, у вторички может не быть.
            page.evaluate("() => document.querySelectorAll('[data-agent=prog]')"
                          ".forEach(e => e.removeAttribute('data-agent'))")
            if not page.evaluate(_MARK_FIELD_JS, [PROGRAM_LABEL, "prog"]):
                continue
            for program in _list_options(page, "prog", 6):
                if time.monotonic() > deadline:
                    out["complete"] = False
                    break
                if _choose(page, "prog", program):
                    out["options"].append({"option": f"{option} → {program}",
                                           **_read(page, "prog")})
        except Exception as exc:                    # noqa: BLE001
            log.debug("Пункт «%s» калькулятора не прочитан: %s", option, exc)
    return out


def summary(result: dict[str, Any]) -> str:
    """Одна строка для условий продукта: что показал калькулятор."""
    parts = []
    for item in result.get("options") or []:
        name = item.get("option") or "калькулятор"
        if not item.get("available"):
            parts.append(f"{name}: недоступно в регионе")
        elif item.get("rate") is not None:
            parts.append(f"{name}: {str(item['rate']).replace('.', ',')} %")
        elif item.get("rate_implied") is not None:
            def rub(v: Any) -> str:
                return f"{int(v):,}".replace(",", " ") + " ₽"
            parts.append(
                f"{name}: платёж {rub(item.get('payment'))} за {rub(item.get('amount'))} на "
                f"{item.get('term_months')} мес — это около "
                f"{str(item['rate_implied']).replace('.', ',')} % годовых (выведено из платежа)")
    region = result.get("region") or "регион не выбран"
    return f"{region} — " + "; ".join(parts) if parts else ""
