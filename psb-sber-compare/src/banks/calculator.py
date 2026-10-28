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

REGION_LABEL = r"регион"
GOAL_LABEL = (r"цель кредита|цель ипотеки|цель|программа|тип недвижимости|"
              r"тип жилья|что покупаете|вид кредита")
DISCOUNT_LABEL = r"зарплат|пенси|перевед[уё] зарплат"
#: Вложенный список после цели: «Квартира в новостройке» → «Программа:
#: Региональная / Семейная / Стандартная» (калькулятор Сбера, 28.10.2026).
PROGRAM_LABEL = r"^программа|программа кредитования|госпрограмм|вид программы|^ипотечная программа"
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
  const labels = Array.from(document.querySelectorAll('body *')).filter(el => {
    const t = (el.textContent || '').trim();
    return t.length > 0 && t.length <= 60 && re.test(t) && el.children.length === 0 && visible(el);
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
  const field = document.querySelector('[data-agent="' + mark + '"]');
  let box = field, best = '';
  for (let i = 0; i < 12 && box; i++, box = box.parentElement) {
    const t = box.innerText || '';
    if (t.length > 9000) break;
    best = t;
    if (/ставк[\\s\\S]{0,60}\\d\\s?%|недоступн/i.test(t) && i >= 2) {
      // Панель результата бывает соседней колонкой: берём ещё уровень.
      const up = box.parentElement && box.parentElement.innerText || '';
      return up.length <= 9000 ? up : t;
    }
  }
  return best;
}
"""


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


def _list_options(page: Any, mark: str, max_options: int) -> list[str]:
    """Пункты выпадающего списка: кликом или из <select>."""
    field = page.locator(f'[data-agent="{mark}"]').first
    options: list[str] = []
    try:
        field.click(timeout=3000)
        page.wait_for_timeout(900)
        options = (page.evaluate(_OPTIONS_JS) or [])[:max_options]
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
    field.click(timeout=3000)
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


def explore(page: Any, region: str, *, max_options: int = 12,
            budget_s: float = 120) -> dict[str, Any] | None:
    """Регион → скидки выключены → каждый пункт списка цели (и вложенного
    списка программы, если он появляется) → результат.

    None — калькулятора с выбором цели на странице нет. Время ограничено
    budget_s: не успели — возвращаем то, что прочитали, а не теряем всё.
    """
    deadline = time.monotonic() + budget_s
    goal = page.evaluate(_MARK_FIELD_JS, [GOAL_LABEL, "goal"])
    region_field = page.evaluate(_MARK_FIELD_JS, [REGION_LABEL, "region"])
    if not goal and not region_field:
        return None
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

    for option in _list_options(page, "goal", max_options):
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
    region = result.get("region") or "регион не выбран"
    return f"{region} — " + "; ".join(parts) if parts else ""
