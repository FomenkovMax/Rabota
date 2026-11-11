"""Движок site_playbook: выбор ЛНР по шагам из конфига и проверка, что регион применился (D-2)."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

# Типовые подписи кнопки выбора города для стратегии "auto".
AUTO_OPENERS = (
    "Ваш город",
    "Выберите город",
    "Выбрать город",
    "Выбрать регион",
    "Регион",
    "Москва",
)


@dataclass
class RegionBinding:
    ok: bool
    method: str
    evidence: str = ""
    reason: str = ""
    rebound: bool = False


def _scope(page: Page, within: str | None):
    return page.locator(within).first if within else page.locator("body")


def verify(page: Page, rule: dict) -> str | None:
    """Фрагмент текста, подтверждающий регион, или None."""
    if rule.get("url_contains") and rule["url_contains"] not in page.url:
        return None
    try:
        text = _scope(page, rule.get("within")).inner_text(timeout=3000)
    except PWTimeout:
        return None
    for needle in rule.get("any_text", []):
        pos = text.find(needle)
        if pos >= 0:
            return " ".join(text[max(0, pos - 40) : pos + len(needle) + 40].split())
    return None


def _run_step(page: Page, step: dict, timeout_ms: int) -> None:
    action = step["action"]
    if action == "goto":
        page.goto(step["url"], timeout=timeout_ms)
    elif action == "click":
        page.locator(step["selector"]).first.click(timeout=timeout_ms)
    elif action == "click_text":
        scope = _scope(page, step.get("within"))
        scope.get_by_text(step["text"], exact=step.get("exact", True)).first.click(
            timeout=timeout_ms
        )
    elif action == "fill":
        page.locator(step["selector"]).first.fill(step["value"], timeout=timeout_ms)
    elif action == "select":
        page.locator(step["selector"]).first.select_option(step["value"], timeout=timeout_ms)
    elif action == "check":
        page.locator(step["selector"]).first.check(timeout=timeout_ms)
    elif action == "wait":
        page.wait_for_timeout(step["ms"])
    else:
        raise ValueError(f"Неизвестное действие playbook: {action}")


def _auto(page: Page, city: str, timeout_ms: int) -> None:
    """Общая стратегия: открыть выбор города, при наличии поиска ввести город, кликнуть его."""
    for label in AUTO_OPENERS:
        opener = page.get_by_text(label, exact=True)
        if opener.count():
            opener.first.click(timeout=timeout_ms)
            break
    else:
        raise LookupError("не найдена кнопка выбора города")
    search = page.locator("input[type=search], input[placeholder*='город' i]")
    if search.count() and search.first.is_visible():
        search.first.fill(city, timeout=timeout_ms)
    page.get_by_text(city, exact=True).last.click(timeout=timeout_ms)


def bind_region(
    page: Page, spec: dict, city: str = "Луганск", navigate: bool = True, timeout_ms: int = 10_000
) -> RegionBinding:
    if navigate:
        page.goto(spec["url"], timeout=timeout_ms * 3)
    rule = spec["verify"]
    method = spec["region_method"]
    already = verify(page, rule)
    if already:
        # Регион уже применён (сайт запомнил выбор) — повторные клики могли бы его сбить.
        return RegionBinding(True, method, already)
    try:
        steps = spec.get("steps") or []
        if steps == "auto":
            _auto(page, city, timeout_ms)
        else:
            for step in steps:
                _run_step(page, step, timeout_ms)
    except (PWTimeout, LookupError) as exc:
        return RegionBinding(False, "not_confirmed", reason=f"шаг не выполнен: {exc}"[:300])
    evidence = verify(page, rule)
    if evidence:
        return RegionBinding(True, method, evidence, rebound=not navigate)
    return RegionBinding(False, "not_confirmed", reason="регион не применился после шагов")
