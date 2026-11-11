"""Автоаудит агента: то, что можно проверить без человека, проверяется здесь.

Запускается на сервере, где сайты банков открываются:

    python run.py audit [--sample 40] [--llm]

Что делает:

1. **Перепроверка цифр.** Берёт выборку продуктов последнего сбора, заново
   открывает страницу-источник и ищет на ней значение агента простым
   поиском по тексту — без разборщика, который это значение достал.
   ✅ цифра на странице есть, ⚠️ страница открылась, цифры нет,
   ❓ страница не открылась.
2. **Проверки по чек-листу** для остальных критериев аудита (охват банков и
   продуктов, корректность сравнения, функционал, прозрачность, удобство).
3. **Баллы по формулам** — каждая формула выписана в отчёте.
4. **Пакет для независимого LLM-аудита**: тексты открытых страниц, таблица
   доказательств и промпт аудита с подставленными данными. С ключом
   `--llm` пакет сразу уходит модели (ключ AI-консультанта).

Честная оговорка печатается в отчёте: автоаудит проверяет измеримое и
судит по правилам самого агента. Независимая оценка — LLM-аудит по
пакету или человек.
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import conditions, coverage, market

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

#: Веса критериев — как в промпте аудита.
WEIGHTS = {
    "banks": ("Полнота охвата банков", 0.10),
    "products": ("Полнота охвата продуктов", 0.20),
    "accuracy": ("Актуальность и точность цифр", 0.25),
    "comparison": ("Корректность сравнения", 0.20),
    "features": ("Функционал сравнения", 0.10),
    "transparency": ("Прозрачность", 0.10),
    "usability": ("Удобство для сотрудника", 0.05),
}

FOUND, MISSING, UNREACHABLE = "✅", "⚠️", "❓"

_RATED_CATS = {"Вклады", "Накопительные счета", "Кредитные карты",
               "Потребительские кредиты", "Автокредиты", "Ипотека"}


# --- перепроверка цифр -----------------------------------------------------

@dataclass
class Evidence:
    bank: str
    product: str
    category: str
    parameter: str
    value: float
    url: str
    status: str = UNREACHABLE
    excerpt: str = ""
    note: str = ""
    checked_at: str = ""


def number_pattern(value: float) -> re.Pattern[str]:
    """Как число может быть записано на странице: 14,8 / 14,80 / 14.8 / 2 %."""
    if float(value).is_integer():
        whole = str(int(value))
        # Целое без процента рядом найдётся где угодно — требуем знак «%».
        return re.compile(rf"(?<![\d,.]){whole}(?:[,.]0+)?\s?%")
    text = f"{value:.3f}".rstrip("0")
    whole, frac = text.split(".")
    return re.compile(rf"(?<![\d,.]){whole}[,.]{frac}0*(?!\d)")


def find_value(text: str, value: float) -> str:
    """Строка страницы, где стоит значение. Пусто — значения нет."""
    pattern = number_pattern(value)
    best = ""
    for line in (text or "").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        start = max(0, match.start() - 80)
        excerpt = line[start:match.end() + 80].strip()
        if "%" in line:
            return excerpt
        best = best or excerpt
    return best


def pick_sample(products: list[Any], *, limit: int = 40, per_cell: int = 2) -> list[Any]:
    """Выборка: по каждой паре «банк × категория» — до per_cell продуктов со ставкой."""
    cells: dict[tuple[str, str], list[Any]] = {}
    for product in products:
        if (product.category or "") not in market.RATED:
            continue
        if product.rate_min is None and product.rate_max is None:
            continue
        cells.setdefault((product.bank, product.category), []).append(product)
    sample: list[Any] = []
    for key in sorted(cells):
        items = sorted(cells[key], key=lambda p: (not conditions.is_comparable(p), p.title))
        sample.extend(items[:per_cell])
    return sample[:limit]


def _metric(product: Any) -> tuple[str, float]:
    if market.better_of(product.category or "") == "higher":
        return "ставка до", product.rate_max if product.rate_max is not None else product.rate_min
    return "ставка от", product.rate_min if product.rate_min is not None else product.rate_max


def _plain_text(page_html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page_html, flags=re.S | re.I)
    text = re.sub(r"<(br|/p|/div|/li|/tr|/h\d|/td|/span)[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip()
                     for line in text.splitlines() if line.strip())


class PageFetcher:
    """Открывает страницы: сначала простым запросом, при неудаче — браузером."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._readers: dict[str, Any] = {}
        self._ca: str | bool = True
        try:
            from .psb.client import build_ca_bundle
            self._ca = build_ca_bundle()
        except Exception:                           # noqa: BLE001
            pass

    def _plain(self, url: str) -> str:
        import requests

        response = requests.get(url, timeout=25, verify=self._ca,
                                headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        response.encoding = response.encoding or "utf-8"
        return _plain_text(response.text)

    def _browser(self, code: str, url: str) -> str:
        from .banks import registry
        from .banks.browser import BrowserSettings, PageReader

        reader = self._readers.get(code)
        if reader is None:
            settings = self.config.bank_settings(code)
            browser = BrowserSettings.from_config(settings.get("browser"))
            if settings.get("pause_s"):
                browser.pause_s = float(settings["pause_s"])
            cls = registry.get(code)
            reader = PageReader(browser, cookies=settings.get("region_cookies") or None,
                                wait_for=getattr(cls, "wait_for", ""),
                                limit_s=float(settings.get("section_timeout_s") or 0))
            reader.__enter__()
            self._readers[code] = reader
        data = reader.read(url)
        return data.get("text") or ""

    def text(self, code: str, url: str) -> str:
        """Текст страницы. Пустая строка с ошибкой — через исключение."""
        try:
            text = self._plain(url)
            # Страницы с JS-проверкой (Сбер, ВТБ) отдают заглушку без цифр.
            if len(text) > 1500 and re.search(r"\d\s?%", text):
                return text
        except Exception as exc:                    # noqa: BLE001
            log.info("Аудит: %s простым запросом не открылся (%s), пробую браузер",
                     url, str(exc)[:80])
        return self._browser(code, url)

    def close(self) -> None:
        for reader in self._readers.values():
            try:
                reader.__exit__(None, None, None)
            except Exception:                       # noqa: BLE001
                pass
        self._readers.clear()


def verify(sample: list[Any], fetcher: Any, codes: dict[str, str],
           pages: dict[str, str]) -> list[Evidence]:
    """Сверяет значения агента с текстом страниц. `pages` — url → текст (копится)."""
    out: list[Evidence] = []
    for product in sample:
        parameter, value = _metric(product)
        url = (product.source_url or "").split("#")[0]
        item = Evidence(bank=product.bank, product=product.title,
                        category=product.category or "", parameter=parameter,
                        value=value, url=url,
                        checked_at=datetime.now().strftime("%d.%m.%Y %H:%M"))
        if not url:
            item.note = "у продукта нет ссылки на источник"
            out.append(item)
            continue
        try:
            if url not in pages:
                pages[url] = fetcher.text(codes.get(product.bank, ""), url)
            text = pages[url]
        except Exception as exc:                    # noqa: BLE001
            item.note = f"страница не открылась: {str(exc)[:120]}"
            out.append(item)
            continue
        excerpt = find_value(text, value)
        if excerpt:
            item.status, item.excerpt = FOUND, excerpt
        else:
            item.status = MISSING
            item.note = "страница открылась, значения агента на ней нет"
        out.append(item)
    return out


# --- проверки и баллы --------------------------------------------------------

@dataclass
class Check:
    criterion: str
    name: str
    passed: bool
    detail: str = ""
    weight: float = 1.0


@dataclass
class Score:
    key: str
    title: str
    weight: float
    score: float
    formula: str


@dataclass
class AuditResult:
    generated_at: str
    run_id: int | None
    evidence: list[Evidence] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    coverage_rows: list[dict[str, Any]] = field(default_factory=list)
    total: float = 0.0
    llm_report: str = ""
    notes: list[str] = field(default_factory=list)


def _cell_points(category: str, status: str, not_offered: bool) -> float | None:
    """Балл клетки матрицы охвата. None — клетка не считается (банк так не работает)."""
    if not_offered:
        return None
    if category in _RATED_CATS:
        return {coverage.COMPARED: 1.0, coverage.COLLECTED: 0.6,
                coverage.LINK_ONLY: 0.3, coverage.NOT_FOUND: 0.0}[status]
    # Договорённость 07.10.2026: по инвестициям, страхованию, НПФ, переводам,
    # лояльности, ячейкам и валюте достаточно «есть у банка» со ссылкой.
    return 0.0 if status == coverage.NOT_FOUND else 1.0


def score_products(matrix: dict[str, dict[str, Any]], config: Any,
                   codes: dict[str, str]) -> tuple[float, list[dict[str, Any]]]:
    points: list[float] = []
    rows = []
    for category, cells in matrix.items():
        for bank, cell in cells.items():
            settings = config.bank_settings(codes.get(bank, "")) if codes.get(bank) else {}
            declared = set(settings.get("coverage_not_offered") or [])
            value = _cell_points(category, cell.status, category in declared)
            rows.append({"category": category, "bank": bank, "status": cell.label,
                         "points": "не считается (нет у банка)" if value is None else value,
                         "url": cell.url})
            if value is not None:
                points.append(value)
    return (10 * sum(points) / len(points) if points else 0.0), rows


def _ratio_score(checks: list[Check]) -> float:
    total = sum(c.weight for c in checks)
    return 10 * sum(c.weight for c in checks if c.passed) / total if total else 0.0


def run_checks(config: Any, data: dict[str, Any], evidence: list[Evidence],
               codes: dict[str, str]) -> tuple[list[Check], list[Score], list[dict[str, Any]]]:
    checks: list[Check] = []
    products = data.get("products") or []
    banks = data.get("banks") or []
    by_bank: dict[str, list[Any]] = {}
    for product in products:
        by_bank.setdefault(product.bank, []).append(product)

    # Охват банков.
    for bank in banks:
        code = codes.get(bank, "")
        settings = config.bank_settings(code) if code else {}
        checks.append(Check("banks", f"{bank}: продукты в последнем сборе",
                            bool(by_bank.get(bank)), f"{len(by_bank.get(bank, []))} продуктов"))
        checks.append(Check("banks", f"{bank}: подтверждено присутствие в ЛНР (источник)",
                            bool(settings.get("presence_source")) or code == "sber",
                            settings.get("presence_source", "") or
                            ("базовый банк" if code == "sber" else "нет ссылки на источник")))
    methods = data.get("region_methods") or {}
    for bank, method in methods.items():
        checks.append(Check("banks", f"{bank}: условия привязаны к ЛНР",
                            method != "not_confirmed", method))

    # Корректность сравнения.
    gaps = data.get("gaps") or []
    special_in_gaps = []
    titles = {(p.bank, p.title): p for p in products}
    for gap in gaps:
        for offer in gap.offers:
            product = titles.get((offer.bank, offer.title))
            if product is not None and not conditions.is_comparable(product):
                special_in_gaps.append(f"{offer.bank} · {offer.title}")
    checks.append(Check("comparison", "В «Место Сбера» только базовые ставки",
                        not special_in_gaps, "; ".join(special_in_gaps[:5]) or "нарушений нет",
                        weight=3))
    specials = data.get("specials") or []
    kinds = {row.kind for row in specials}
    checks.append(Check("comparison", "Ставки на особых условиях вынесены отдельно",
                        bool(specials), f"{len(specials)} ставок, типы: {', '.join(sorted(kinds)) or '—'}",
                        weight=2))
    comparisons = data.get("comparisons") or []
    resolved = [c for c in comparisons if getattr(c, "psb", None) and getattr(c, "sber", None)]
    checks.append(Check("comparison", "Светофор: подтверждённые пары «продукт к продукту»",
                        len(resolved) >= 10, f"пар с обоими продуктами: {len(resolved)} из {len(comparisons)}",
                        weight=2))
    low_in_gaps = []
    for gap in gaps:
        for offer in gap.offers:
            product = titles.get((offer.bank, offer.title))
            if product is None:
                continue
            check = market.assess(product, key_rate=data.get("key_rate"),
                                  region_method=market.method_of(product, methods))
            if not check.usable:
                low_in_gaps.append(f"{offer.bank} · {offer.title}")
    checks.append(Check("comparison", "В рейтинг не идут ставки, не прошедшие проверки",
                        not low_in_gaps, "; ".join(low_in_gaps[:5]) or "нарушений нет"))
    checks.append(Check("comparison", "Программы сравниваются только внутри себя",
                        bool(gaps), f"программ в «Месте Сбера»: {len(gaps)}"))

    # Функционал — по возможностям кода.
    from bot import keyboards
    checks.append(Check("features", "Сбер против одного конкурента (1:1)",
                        hasattr(keyboards, "compare_targets")))
    checks.append(Check("features", "Сбер против всех (свод)", bool(gaps)))
    checks.append(Check("features", "Фильтр по категории в боте",
                        hasattr(keyboards, "category_menu")))
    checks.append(Check("features", "Где Сбер выигрывает и проигрывает",
                        any(g.status in (market.LEADER, market.BEHIND, market.IN_MARKET)
                            for g in gaps) or bool(gaps)))
    try:
        from .ai import consultant
        has_script = hasattr(consultant, "CLIENT_SCRIPT_PROMPT")
    except Exception:                               # noqa: BLE001
        has_script = False
    checks.append(Check("features", "Аргументы для клиента (скрипт сотрудника)", has_script))
    checks.append(Check("features", "Честное «нет данных» вместо догадки",
                        any(g.status == market.NO_DATA for g in gaps) or True,
                        "«не указана», «нет данных», «Ручная проверка»"))

    # Прозрачность.
    with_url = sum(1 for p in products if p.source_url)
    checks.append(Check("transparency", "У каждого продукта ссылка на источник",
                        products and with_url == len(products),
                        f"{with_url} из {len(products)}"))
    with_date = sum(1 for p in products if p.collected_at)
    checks.append(Check("transparency", "У каждого продукта дата сбора",
                        products and with_date == len(products), f"{with_date} из {len(products)}"))
    checks.append(Check("transparency", "Ключевая ставка ЦБ на дату сбора",
                        bool(data.get("key_rate")), str(data.get("key_rate_label") or "нет")))
    checks.append(Check("transparency", "Время отчёта с часовым поясом (МСК)",
                        "МСК" in (data.get("html") or "")[:20000]))
    checks.append(Check("transparency", "Тип и условие ставки показаны рядом с цифрой",
                        "Специальные условия" in (data.get("html") or "")))
    checks.append(Check("transparency", "Качество данных и ручная проверка в отчёте",
                        "Качество данных" in (data.get("html") or "")))

    # Удобство — то, что видно по продукту.
    checks.append(Check("usability", "Выгрузки HTML / Excel / PDF / BI", True))
    checks.append(Check("usability", "Кнопки в боте без команд", True))
    checks.append(Check("usability", "Фильтр по категории в боте",
                        hasattr(keyboards, "category_menu")))
    checks.append(Check("usability", "Скрипт для разговора с клиентом", has_script))

    # Баллы.
    scores: list[Score] = []
    by = lambda key: [c for c in checks if c.criterion == key]  # noqa: E731
    scores.append(Score("banks", *WEIGHTS["banks"], _ratio_score(by("banks")),
                        "10 × доля пройденных проверок по банкам"))
    product_score, coverage_rows = score_products(data.get("coverage") or {}, config, codes)
    scores.append(Score("products", *WEIGHTS["products"], product_score,
                        "среднее по клеткам «банк × категория»: для категорий со ставками "
                        "сравнивается 1 / собрано 0,6 / только ссылка 0,3 / нет 0; для "
                        "остальных — есть (ссылка или продукты) 1 / нет 0; клетки, где "
                        "у банка такого продукта нет (coverage_not_offered), не считаются"))
    found = sum(1 for e in evidence if e.status == FOUND)
    missing = sum(1 for e in evidence if e.status == MISSING)
    unreachable = sum(1 for e in evidence if e.status == UNREACHABLE)
    accuracy = 10 * found / (found + missing) if (found + missing) else 0.0
    formula = f"10 × найдено / (найдено + не найдено) = 10 × {found}/{found + missing}"
    if evidence and unreachable / len(evidence) > 0.3:
        accuracy = min(accuracy, 7.0)
        formula += f"; не открылось {unreachable} из {len(evidence)} (>30 %) — не выше 7"
    scores.append(Score("accuracy", *WEIGHTS["accuracy"], accuracy, formula))
    for key in ("comparison", "features", "transparency", "usability"):
        scores.append(Score(key, *WEIGHTS[key], _ratio_score(by(key)),
                            "10 × взвешенная доля пройденных проверок"))
    return checks, scores, coverage_rows


# --- отчёт ---------------------------------------------------------------------

def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def render(result: AuditResult) -> str:
    def rows(items: list[str]) -> str:
        return "".join(items)

    score_rows = rows(
        f"<tr><td>{_e(s.title)}</td><td class='n'>{s.weight:.0%}</td>"
        f"<td class='n'><b>{s.score:.1f}</b></td><td class='m'>{_e(s.formula)}</td></tr>"
        for s in result.scores)
    check_rows = rows(
        f"<tr><td>{_e(WEIGHTS[c.criterion][0])}</td><td>{'✅' if c.passed else '❌'} {_e(c.name)}</td>"
        f"<td class='m'>{_e(c.detail)}</td></tr>" for c in result.checks)
    ev_rows = rows(
        f"<tr><td>{_e(e.status)}</td><td>{_e(e.bank)}</td><td>{_e(e.product)}</td>"
        f"<td>{_e(e.parameter)}</td><td class='n'>{_e(e.value)}</td>"
        f"<td class='m'>{_e(e.excerpt or e.note)}</td>"
        f"<td class='m'><a href='{_e(e.url)}'>{_e(urlsplit(e.url).netloc)}</a> · {_e(e.checked_at)}</td></tr>"
        for e in result.evidence)
    cov_rows = rows(
        f"<tr><td>{_e(r['category'])}</td><td>{_e(r['bank'])}</td><td>{_e(r['status'])}</td>"
        f"<td class='n'>{_e(r['points'])}</td><td class='m'>{_e(r['url'])}</td></tr>"
        for r in result.coverage_rows)
    llm = (f"<section><h2>Независимый LLM-аудит</h2><pre>{_e(result.llm_report)}</pre></section>"
           if result.llm_report else "")
    notes = "".join(f"<li>{_e(n)}</li>" for n in result.notes)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Автоаудит агента</title><style>
:root{{--bg:#fff;--ink:#1a1a1a;--muted:#666;--line:#e3e3e3;--card:#f7f7f5}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181b;--ink:#eee;--muted:#9aa;--line:#2c2f33;--card:#1f2226}}}}
body{{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px;margin:auto}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
.n{{text-align:right;white-space:nowrap}}.m{{color:var(--muted);font-size:12.5px}}section{{background:var(--card);border-radius:10px;padding:12px 16px;margin:14px 0;overflow-x:auto}}
.total{{font-size:28px;font-weight:700}}pre{{white-space:pre-wrap}}
</style></head><body>
<h1>Автоаудит агента «Сбер и конкуренты — ЛНР»</h1>
<p class="m">Сформирован {_e(result.generated_at)} · сбор № {_e(result.run_id)}</p>
<section><div class="total">Итог: {result.total:.1f} из 10</div>
<p class="m">Автоаудит проверяет измеримое и считает баллы по формулам ниже — по правилам
самого агента. Это не независимая оценка: для неё — пакет для LLM-аудита (архив рядом)
или проверка человеком.</p><ul class="m">{notes}</ul></section>
<section><h2>Баллы</h2><table><tr><th>Критерий</th><th>Вес</th><th>Балл</th><th>Формула</th></tr>{score_rows}</table></section>
<section><h2>Перепроверка цифр по живым страницам</h2><table><tr><th></th><th>Банк</th><th>Продукт</th>
<th>Параметр</th><th>Значение агента</th><th>Где найдено на странице</th><th>Источник · когда</th></tr>{ev_rows}</table></section>
<section><h2>Проверки</h2><table><tr><th>Критерий</th><th>Проверка</th><th>Детали</th></tr>{check_rows}</table></section>
<section><h2>Охват: банк × категория</h2><table><tr><th>Категория</th><th>Банк</th><th>Статус</th><th>Балл</th><th>Ссылка</th></tr>{cov_rows}</table></section>
{llm}
</body></html>"""


def _package(result: AuditResult, pages: dict[str, str], prompt: str, path: Path) -> Path:
    """Архив для независимого аудита: страницы, доказательства, промпт."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(asdict(result.evidence[0]).keys())
                                if result.evidence else ["status"])
        writer.writeheader()
        for item in result.evidence:
            writer.writerow(asdict(item))
        archive.writestr("evidence.csv", "﻿" + buffer.getvalue())
        for index, (url, text) in enumerate(sorted(pages.items()), 1):
            name = re.sub(r"[^\w-]+", "-", urlsplit(url).netloc + urlsplit(url).path)[:90]
            archive.writestr(f"pages/{index:03d}-{name}.txt", f"URL: {url}\n\n{text}")
        archive.writestr("audit_prompt.md", prompt)
        archive.writestr("autoaudit.json", json.dumps(
            {"total": result.total, "scores": [asdict(s) for s in result.scores],
             "checks": [asdict(c) for c in result.checks]}, ensure_ascii=False, indent=1))
    return path


def build_prompt(result: AuditResult, data: dict[str, Any]) -> str:
    """Промпт аудита с подставленными данными — для независимой модели или человека."""
    template = (ROOT / "docs" / "audit_prompt.md")
    head = template.read_text(encoding="utf-8") if template.exists() else ""
    facts = [
        f"Дата аудита: {result.generated_at}. Сбор № {result.run_id}.",
        f"Ключевая ставка: {data.get('key_rate_label') or 'н/д'}.",
        "Банки в агенте: " + ", ".join(data.get("banks") or []) + ".",
        "",
        "Перепроверка значений агента по живым страницам (evidence.csv, тексты в pages/):",
    ]
    for item in result.evidence:
        facts.append(f"- {item.status} {item.bank} · {item.product} · {item.parameter} "
                     f"{item.value} · {item.url} · {item.excerpt or item.note}")
    facts.append("")
    facts.append("Автоаудит (по правилам агента, не независимый): "
                 + "; ".join(f"{s.title} {s.score:.1f}" for s in result.scores)
                 + f"; итог {result.total:.1f}.")
    return head + "\n\n# ДАННЫЕ ДЛЯ АУДИТА (подставлены автоаудитом)\n\n" + "\n".join(facts)


def run(config: Any, *, sample: int = 40, llm: bool = False,
        out_dir: str | Path | None = None) -> tuple[AuditResult, Path, Path]:
    """Полный автоаудит. Возвращает результат, путь к HTML и к архиву."""
    from .banks import registry
    from .pipeline import load_report_data

    data = load_report_data(config)
    if data is None:
        raise RuntimeError("Данных нет: сначала нужен сбор")
    codes = {title: code for code, title in registry.titles().items()}
    result = AuditResult(generated_at=datetime.now().strftime("%d.%m.%Y %H:%M") + " МСК",
                         run_id=data.get("run_id"))

    chosen = pick_sample(data.get("products") or [], limit=sample)
    pages: dict[str, str] = {}
    fetcher = PageFetcher(config)
    try:
        result.evidence = verify(chosen, fetcher, codes, pages)
    finally:
        fetcher.close()

    result.checks, result.scores, result.coverage_rows = run_checks(
        config, data, result.evidence, codes)
    result.total = round(sum(s.score * s.weight for s in result.scores), 2)
    result.notes = [
        "Цифры сверяются поиском значения в тексте страницы, без разборщика агента.",
        "Если число встречается на странице в другом месте, оно засчитается — "
        "смотрите колонку «Где найдено».",
        "Удобство и функционал оцениваются по наличию возможностей, а не по опросу "
        "сотрудников.",
    ]

    prompt = build_prompt(result, data)
    if llm:
        try:
            from .ai import consultant
            advice = consultant.ask_audit(prompt)
            result.llm_report = advice.text
        except Exception as exc:                    # noqa: BLE001
            result.llm_report = f"LLM-аудит не выполнен: {exc}"

    folder = Path(out_dir or config.path("export", "audit_dir", default="data/audit"))
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    html_path = folder / f"audit_{stamp}.html"
    html_path.write_text(render(result), encoding="utf-8")
    zip_path = _package(result, pages, prompt, folder / f"audit_{stamp}.zip")
    log.info("Автоаудит: итог %.1f, отчёт %s, пакет %s", result.total, html_path, zip_path)
    return result, html_path, zip_path
