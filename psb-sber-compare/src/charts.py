"""Графики и выводы для обзора в начале отчёта.

Всё рисуется встроенным SVG, без внешних библиотек: отчёт открывают из
Telegram — на телефоне и на компьютере, в том числе без интернета.
Подсказка при наведении — стандартный <title>; на телефоне наведения нет,
поэтому главные значения подписаны прямо на графике.

Данные — те же, что в таблицах отчёта (Gap, QualityRow, SpecialRow,
Comparison): графики ничего не считают заново и не додумывают.
"""

from __future__ import annotations

import statistics
from html import escape
from typing import Any, Iterable

from . import brand

LEADER, IN_MARKET, BEHIND, NO_SBER = "лидер", "в рынке", "отстаёт", "не найдено у Сбера"
NO_LNR = "нет в ЛНР у Сбера"
STATUS_VAR = {LEADER: "--st-good", IN_MARKET: "--st-warning", BEHIND: "--st-critical",
              NO_SBER: "--ink-muted", NO_LNR: "--st-critical"}
STATUS_ICON = {LEADER: "▲", IN_MARKET: "■", BEHIND: "▼", NO_SBER: "○", NO_LNR: "⛔"}


def e(value: Any) -> str:
    return escape(str(value), quote=True)


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",") + " %"


def pp(value: float) -> str:
    return f"{abs(value):.2f}".replace(".", ",") + " п.п."


def genitive(bank: str) -> str:
    """«у Сбера», «у ПСБ»: склоняется только Сбер, аббревиатуры — нет."""
    return {"Сбер": "Сбера", "Т-Банк": "Т-Банка", "РостФинанс": "РостФинанса"}.get(bank, bank)


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _svg(width: int, height: int, label: str) -> str:
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(label)}" '
            f'style="font-family:inherit">')


# --- выводы ---------------------------------------------------------------

def insights(gaps: list[Any], *, home: str, comparisons: list[Any] | None = None,
             specials: list[Any] | None = None, quality_rows: list[Any] | None = None,
             changes: list[Any] | None = None,
             lnr_total: dict[str, int] | None = None) -> list[tuple[str, str]]:
    """Короткие выводы по данным отчёта: (статус-цвет, текст).

    Правила простые и проверяемые: каждая фраза опирается на строку одной из
    таблиц ниже. Модель здесь не участвует — выводы не меняются от запуска
    к запуску и не содержат того, чего нет в данных.
    """
    out: list[tuple[str, str]] = []
    if lnr_total and sum(lnr_total.values()):
        n = sum(lnr_total.values())
        known = n - lnr_total.get("unknown", 0)
        out.append(("--s1" if known == n else "--st-warning",
                    f"Наличие в ЛНР установлено у {known} из {n} продуктов {genitive(home)}: "
                    f"с условиями ЛНР — {lnr_total.get('lnr', 0)}, с общероссийскими — "
                    f"{lnr_total.get('federal', 0)}, нет в ЛНР — {lnr_total.get('absent', 0)}."))
    rated = [g for g in gaps if g.status in (LEADER, IN_MARKET, BEHIND)]
    if rated:
        lead = [g for g in rated if g.status == LEADER]
        behind = [g for g in rated if g.status == BEHIND]
        out.append(("--s1", f"{home} сравнён с рынком по {len(rated)} программам: "
                            f"лидирует в {len(lead)}, в рынке — "
                            f"{len(rated) - len(lead) - len(behind)}, отстаёт в {len(behind)}."))
        if behind:
            worst = max(behind, key=lambda g: abs(g.delta_vs_best or 0))
            prefix = "до" if worst.better == "higher" else "от"
            out.append(("--st-critical",
                        f"Сильнее всего {home} отстаёт в программе «{worst.program}»: "
                        f"{prefix} {pct(worst.sber.value)} против {prefix} "
                        f"{pct(worst.best.value)} у {genitive(worst.best.bank)} — разница "
                        f"{pp(worst.delta_vs_best or 0)}"))
        if lead:
            best = max(lead, key=lambda g: g.advantage or 0)
            out.append(("--st-good",
                        f"Самое сильное преимущество — «{best.program}»: на "
                        f"{pp(best.advantage or 0)} выгоднее клиенту, чем медиана "
                        f"остальных банков."))
    absent = [g for g in gaps if g.status == NO_LNR]
    if absent:
        names = ", ".join(f"«{g.program}»" for g in absent[:5])
        more = f" и ещё {len(absent) - 5}" if len(absent) > 5 else ""
        out.append(("--st-critical", f"В ЛНР {home} не выдаёт: {names}{more} — подтверждено "
                                     "калькулятором на сайте банка; у конкурентов эти "
                                     "программы есть."))
    missing = [g for g in gaps if g.status == NO_SBER]
    if missing:
        names = ", ".join(f"«{g.program}»" for g in missing[:4])
        more = f" и ещё {len(missing) - 4}" if len(missing) > 4 else ""
        out.append(("--ink-muted", f"Программы конкурентов, которых сбор не нашёл у "
                                   f"{genitive(home)}: {names}{more}. Проверить, есть ли "
                                   f"они на сайте."))

    if comparisons:
        win = sum(1 for c in comparisons if c.light == "green")
        lose = sum(1 for c in comparisons if c.light == "red")
        out.append(("--s1", f"Светофор по парам продуктов: выигрываем в {win}, "
                            f"проигрываем в {lose} из {len(comparisons)}."))

    if specials:
        rivals = [s for s in specials if s.bank != home and s.rate is not None]
        if rivals:
            top = max((s for s in rivals if s.category in ("Вклады", "Накопительные счета")),
                      key=lambda s: s.rate, default=None)
            text = (f"У конкурентов {len(rivals)} ставок на особых условиях — в рейтинг "
                    f"они не входят.")
            if top is not None:
                text += (f" Самая высокая по сбережениям: {top.bank}, «{top.title}» — "
                         f"{pct(top.rate)} ({top.kind_label}).")
            out.append(("--st-warning", text))

    if quality_rows:
        own = [q for q in quality_rows if q.bank == home and q.rated]
        if own:
            rated_n = sum(q.rated for q in own)
            usable = sum(q.usable for q in own)
            share = round(100 * usable / rated_n) if rated_n else 0
            tone = "--st-good" if share >= 80 else "--st-warning" if share >= 60 else "--st-critical"
            out.append((tone, f"Ставка {genitive(home)} найдена и проверена у {usable} из {rated_n} "
                              f"продуктов ({share} %)."))

    if changes:
        own = sum(1 for c in changes if c.get("bank") == home)
        out.append(("--ink-2", f"Изменений с прошлого сбора: {len(changes)}, из них у "
                               f"{genitive(home)} — {own}."))
    return out


def insights_block(items: list[tuple[str, str]]) -> str:
    if not items:
        return '<p class="empty">Выводов пока нет: нужен сбор со Сбером и конкурентами.</p>'
    rows = "".join(
        f'<li><i style="background:var({var})"></i><span>{e(text)}</span></li>'
        for var, text in items)
    return f'<ul class="ins">{rows}</ul>'


# --- «капельный» график: Сбер на фоне рынка --------------------------------

def dumbbell(gaps: list[Any], *, home: str) -> str:
    """Каждая программа — линия от худшей до лучшей ставки рынка.

    Точки конкурентов — цветом банка, вертикальная черта — медиана остальных,
    крупная точка — Сбер в цвете статуса. Ось у каждой строки своя
    (вклад 13 % и ипотека 6 % на одной оси слиплись бы), поэтому
    подписаны края диапазона.
    """
    rows = [g for g in gaps if g.sber is not None and len(g.offers) >= 2]
    if not rows:
        return ""
    rows.sort(key=lambda g: (g.advantage or 0))
    row_h, pad_l, pad_r, top = 40, 230, 120, 10
    width = 1080
    plot = width - pad_l - pad_r
    height = top + len(rows) * row_h + 30
    parts = [_svg(width, height, f"{home} на фоне рынка по программам")]
    for index, g in enumerate(rows):
        y = top + index * row_h + row_h / 2
        values = [o.value for o in g.offers]
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        # «Лучше» всегда справа: для кредитов ось развёрнута.
        def x(v: float) -> float:
            if high == low:             # все банки с одной ставкой
                return pad_l + plot / 2
            share = (v - low) / span if g.better == "higher" else (high - v) / span
            return pad_l + 20 + share * (plot - 40)

        worse_v, better_v = (low, high) if g.better == "higher" else (high, low)
        parts.append(
            f'<text x="{pad_l - 14}" y="{y + 4}" text-anchor="end" font-size="13" '
            f'fill="var(--ink)">{e(_short(g.program, 30))}</text>'
            f'<line x1="{pad_l + 20}" y1="{y}" x2="{pad_l + plot - 20}" y2="{y}" '
            f'stroke="var(--grid)" stroke-width="6" stroke-linecap="round"/>'
            f'<text x="{pad_l + 20}" y="{y + 18}" font-size="10.5" fill="var(--ink-muted)" '
            f'text-anchor="middle">{e(pct(worse_v))}</text>'
            f'<text x="{pad_l + plot - 20}" y="{y + 18}" font-size="10.5" '
            f'fill="var(--ink-muted)" text-anchor="middle">{e(pct(better_v))}</text>')
        if g.others_median is not None:
            mx = x(g.others_median)
            parts.append(f'<line x1="{mx:.1f}" y1="{y - 9}" x2="{mx:.1f}" y2="{y + 9}" '
                         f'stroke="var(--ink-2)" stroke-width="2">'
                         f'<title>Медиана остальных: {e(pct(g.others_median))}</title></line>')
        for o in g.offers:
            if o.bank == home:
                continue
            parts.append(f'<circle cx="{x(o.value):.1f}" cy="{y}" r="6" fill="{brand.color(o.bank)}" '
                         f'stroke="var(--surface)" stroke-width="2">'
                         f'<title>{e(o.bank)} · {e(o.title)}: {e(pct(o.value))}</title></circle>')
        var = STATUS_VAR.get(g.status, "--s1")
        sx = x(g.sber.value)
        parts.append(f'<circle cx="{sx:.1f}" cy="{y}" r="8.5" fill="var({var})" '
                     f'stroke="var(--surface)" stroke-width="2.5">'
                     f'<title>{e(home)} · {e(g.sber.title)}: {e(pct(g.sber.value))} — '
                     f'{e(g.status)}, место {e(g.place)}</title></circle>'
                     f'<text x="{width - pad_r + 12}" y="{y + 4}" font-size="12.5" '
                     f'font-weight="600" fill="var(--ink)">{e(pct(g.sber.value))}</text>'
                     f'<text x="{width - pad_r + 12}" y="{y + 18}" font-size="11" '
                     f'fill="var(--ink-muted)">{e(STATUS_ICON.get(g.status, ""))} '
                     f'{e(g.place)}</text>')
    parts.append(
        f'<text x="{pad_l + 20}" y="{height - 4}" font-size="11.5" fill="var(--ink-muted)">'
        f'← хуже для клиента</text>'
        f'<text x="{pad_l + plot - 20}" y="{height - 4}" font-size="11.5" text-anchor="end" '
        f'fill="var(--ink-muted)">лучше для клиента →</text></svg>')
    legend = (
        '<div class="legend">'
        f'<span><i style="background:var(--st-good);border-radius:50%"></i>{e(home)} — лидер</span>'
        '<span><i style="background:var(--st-warning);border-radius:50%"></i>в рынке</span>'
        '<span><i style="background:var(--st-critical);border-radius:50%"></i>отстаёт</span>'
        + "".join(f'<span><i style="background:{brand.color(b)};border-radius:50%"></i>{e(b)}</span>'
                  for b in sorted({o.bank for g in gaps for o in g.offers if o.bank != home}))
        + '<span><i style="background:var(--ink-2);width:3px"></i>медиана остальных</span>'
        '</div>')
    # На телефоне широкий график листается вбок, а не сжимается в нечитаемое.
    return legend + '<div class="wide">' + "".join(parts) + "</div>"


# --- пузырьки: позиционирование банков -------------------------------------

def bubbles(gaps: list[Any], *, home: str) -> str:
    """Банк — пузырь: X — средняя ставка по сбережениям (правее — выгоднее
    вкладчику), Y — средняя ставка по кредитам наличными, рефинансированию,
    автокредиту и залогу (выше — выгоднее заёмщику), размер — в скольких
    программах банк есть с проверенной ставкой.
    """
    save: dict[str, list[float]] = {}
    loan: dict[str, list[float]] = {}
    seen: dict[str, int] = {}
    for g in gaps:
        for o in g.offers:
            seen[o.bank] = seen.get(o.bank, 0) + 1
            if g.block == "DEP":
                save.setdefault(o.bank, []).append(o.value)
            elif g.block == "LOAN":
                loan.setdefault(o.bank, []).append(o.value)
    banks = [b for b in seen if b in save and b in loan]
    if len(banks) < 2:
        return ""
    pts = {b: (statistics.fmean(save[b]), statistics.fmean(loan[b]), seen[b]) for b in banks}
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    x0, x1 = min(xs) - 0.4, max(xs) + 0.4
    y0, y1 = min(ys) - 0.6, max(ys) + 0.6
    width, height, pad_l, pad_b, pad_t, pad_r = 1080, 420, 70, 46, 20, 30
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b
    biggest = max(p[2] for p in pts.values())

    def px(v: float) -> float:
        return pad_l + (v - x0) / (x1 - x0) * pw

    def py(v: float) -> float:          # кредит дешевле — выше
        return pad_t + (v - y0) / (y1 - y0) * ph

    parts = [_svg(width, height, "Позиционирование банков: сбережения и кредиты")]
    mx, my = px(statistics.median(xs)), py(statistics.median(ys))
    parts.append(
        f'<line x1="{mx:.1f}" y1="{pad_t}" x2="{mx:.1f}" y2="{pad_t + ph}" stroke="var(--grid)" '
        f'stroke-dasharray="4 4"/>'
        f'<line x1="{pad_l}" y1="{my:.1f}" x2="{pad_l + pw}" y2="{my:.1f}" stroke="var(--grid)" '
        f'stroke-dasharray="4 4"/>'
        f'<text x="{pad_l + pw - 6}" y="{pad_t + 14}" text-anchor="end" font-size="11.5" '
        f'fill="var(--ink-muted)">выгодно и вкладчику, и заёмщику</text>'
        f'<text x="{pad_l + 6}" y="{pad_t + ph - 8}" font-size="11.5" '
        f'fill="var(--ink-muted)">дорогие кредиты, низкие ставки по вкладам</text>'
        f'<line x1="{pad_l}" y1="{pad_t + ph}" x2="{pad_l + pw}" y2="{pad_t + ph}" '
        f'stroke="var(--axis)"/>'
        f'<text x="{pad_l + pw / 2}" y="{height - 8}" text-anchor="middle" font-size="12" '
        f'fill="var(--ink-2)">Средняя ставка по сбережениям, % → выгоднее вкладчику</text>'
        f'<text x="16" y="{pad_t + ph / 2}" font-size="12" fill="var(--ink-2)" '
        f'transform="rotate(-90 16 {pad_t + ph / 2})" text-anchor="middle">'
        f'Средняя ставка по кредитам, % (ниже — дороже)</text>')
    for v in (x0 + 0.4, (x0 + x1) / 2, x1 - 0.4):
        parts.append(f'<text x="{px(v):.1f}" y="{pad_t + ph + 16}" text-anchor="middle" '
                     f'font-size="11" fill="var(--ink-muted)">{e(pct(v, 1))}</text>')
    for v in (y0 + 0.6, (y0 + y1) / 2, y1 - 0.6):
        parts.append(f'<text x="{pad_l - 8}" y="{py(v) + 4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="var(--ink-muted)">{e(pct(v, 1))}</text>')
    # Крупные — снизу, чтобы мелкие не прятались.
    for bank, (sx, sy, n) in sorted(pts.items(), key=lambda kv: -kv[1][2]):
        r = 12 + 22 * (n / biggest) ** 0.5
        own = bank == home
        fill = brand.color(bank)
        parts.append(
            f'<circle cx="{px(sx):.1f}" cy="{py(sy):.1f}" r="{r:.1f}" fill="{fill}" '
            f'fill-opacity="{0.85 if own else 0.55}" stroke="{fill}" stroke-width="2">'
            f'<title>{e(bank)}: сбережения {e(pct(sx))}, кредиты {e(pct(sy))}, '
            f'программ {n}</title></circle>'
            f'<text x="{px(sx):.1f}" y="{py(sy) + 4:.1f}" text-anchor="middle" font-size="12" '
            f'font-weight="700" fill="#fff" paint-order="stroke" stroke="rgba(0,0,0,.35)" '
            f'stroke-width="2">{e(bank)}</text>')
    parts.append("</svg>")
    return '<div class="wide">' + "".join(parts) + "</div>"


# --- воронка данных --------------------------------------------------------

_FUNNEL_STEPS = ("--f1", "--f2", "--f3", "--f4")


def funnel(quality_rows: list[Any], gaps: list[Any]) -> str:
    """Сколько продуктов доходит до сравнения: от собранных до рейтинга."""
    rated = sum(q.rated for q in quality_rows)
    if not rated:
        return ""
    found = sum(q.with_rate for q in quality_rows)
    usable = sum(q.usable for q in quality_rows)
    ranked = sum(len(g.offers) for g in gaps)
    stages = [
        ("Продуктов, где ставка — главный параметр", rated),
        ("Ставка найдена на странице", found),
        ("Ставка прошла проверки", usable),
        ("Лучшие базовые ставки программ — в рейтинге", ranked),
    ]
    width, row_h, gap_h = 520, 46, 8
    height = len(stages) * (row_h + gap_h)
    center = width / 2
    parts = [_svg(width, height, "Воронка данных: от собранных продуктов до рейтинга")]
    for index, (label, value) in enumerate(stages):
        w = max(200.0, (width - 20) * value / rated)
        y = index * (row_h + gap_h)
        share = round(100 * value / rated)
        ink = "#fff" if index >= 2 else "var(--ink)"
        parts.append(
            f'<rect x="{center - w / 2:.1f}" y="{y}" width="{w:.1f}" height="{row_h}" rx="6" '
            f'fill="var({_FUNNEL_STEPS[index]})"><title>{e(label)}: {value} ({share} %)</title></rect>'
            f'<text x="{center}" y="{y + 20}" text-anchor="middle" font-size="13.5" '
            f'font-weight="650" fill="{ink}">{value} · {share} %</text>'
            f'<text x="{center}" y="{y + 37}" text-anchor="middle" font-size="11.5" '
            f'fill="{ink}" fill-opacity=".85">{e(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --- статусы по блокам -----------------------------------------------------

def status_bars(gaps: list[Any], block_names: dict[str, str]) -> str:
    """100 % столбики: из чего складывается место Сбера в каждом блоке."""
    order = (LEADER, IN_MARKET, BEHIND, NO_LNR, NO_SBER)
    blocks: dict[str, dict[str, int]] = {}
    for g in gaps:
        if g.status in order:
            blocks.setdefault(g.block, {}).setdefault(g.status, 0)
            blocks[g.block][g.status] += 1
    if not blocks:
        return ""
    width, row_h, pad_l, pad_r = 520, 30, 110, 10
    plot = width - pad_l - pad_r
    height = len(blocks) * (row_h + 14) + 4
    parts = [_svg(width, height, "Статусы Сбера по блокам продуктов")]
    for index, (block, counts) in enumerate(blocks.items()):
        y = index * (row_h + 14)
        total = sum(counts.values())
        parts.append(f'<text x="{pad_l - 12}" y="{y + row_h / 2 + 5}" text-anchor="end" '
                     f'font-size="13" fill="var(--ink)">{e(block_names.get(block, block))}</text>')
        x = pad_l
        for status in order:
            n = counts.get(status, 0)
            if not n:
                continue
            w = plot * n / total
            ink = "#0b0b0b" if status == IN_MARKET else "#fff"
            parts.append(
                f'<rect x="{x + 1:.1f}" y="{y}" width="{max(2.0, w - 2):.1f}" height="{row_h}" '
                f'rx="4" fill="var({STATUS_VAR[status]})"><title>{e(status)}: {n}</title></rect>')
            if w > 44:
                parts.append(f'<text x="{x + w / 2:.1f}" y="{y + row_h / 2 + 5}" '
                             f'text-anchor="middle" font-size="12.5" font-weight="650" '
                             f'fill="{ink}">{STATUS_ICON[status]} {n}</text>')
            x += w
    parts.append("</svg>")
    legend = '<div class="legend">' + "".join(
        f'<span><i style="background:var({STATUS_VAR[s]})"></i>{STATUS_ICON[s]} {e(s)}</span>'
        for s in order) + "</div>"
    return legend + "".join(parts)


# --- тепловая карта: программа × банк --------------------------------------

def heatmap(gaps: list[Any], banks: Iterable[str], *, home: str) -> str:
    """Ставка банка в программе и её отклонение от медианы всех банков.

    Синий — выгоднее клиенту, чем медиана, красный — дороже/ниже. Цвет
    дублирован числом в ячейке, так что читается и без цвета.
    """
    rows = [g for g in gaps if len(g.offers) >= 2]
    if not rows:
        return ""
    banks = list(banks)
    head = "".join(f'<th class="{"own" if b == home else ""}">{brand.name(b)}</th>' for b in banks)
    body = []
    for g in rows:
        values = {o.bank: o.value for o in g.offers}
        med = statistics.median(values.values())
        cells = []
        for b in banks:
            v = values.get(b)
            if v is None:
                cells.append('<td class="hm none">—</td>')
                continue
            adv = (v - med) if g.better == "higher" else (med - v)
            level = min(3, int(abs(adv) / 0.5 + 0.5)) if abs(adv) >= 0.25 else 0
            tone = "" if level == 0 else ("b" if adv > 0 else "r") + str(level)
            sign = "+" if adv >= 0.05 else "−" if adv <= -0.05 else ""
            dev = f"{abs(adv):.1f}".replace(".", ",")
            tip = (f"{b} · {g.program}: {pct(v)}; "
                   f"{'выгоднее' if adv > 0 else 'хуже'} медианы на {pp(adv)}" if level
                   else f"{b} · {g.program}: {pct(v)}; на уровне медианы")
            cells.append(f'<td class="hm {tone}{" own" if b == home else ""}" title="{e(tip)}">'
                         f'{e(pct(v))}<small>{sign}{dev}</small></td>')
        body.append(f'<tr><td class="pname">{e(g.program)}</td>{"".join(cells)}</tr>')
    legend = (
        '<div class="legend"><span><i class="hm b3"></i>заметно выгоднее клиенту</span>'
        '<span><i class="hm b1"></i>чуть выгоднее</span><span><i class="hm"></i>на уровне медианы</span>'
        '<span><i class="hm r1"></i>чуть хуже</span><span><i class="hm r3"></i>заметно хуже</span>'
        '<span>число под ставкой — отклонение от медианы, п.п.</span></div>')
    return (legend + '<div class="scroll"><table class="heat"><thead><tr><th>Программа</th>'
            f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


CSS = """
.ins{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.ins li{display:flex;gap:12px;align-items:flex-start;font-size:14.5px;line-height:1.5}
.ins li i{flex:0 0 4px;align-self:stretch;border-radius:2px;min-height:20px}
.duo{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}
.duo .card{margin-bottom:0}
table.heat td.hm{text-align:center;font-variant-numeric:tabular-nums;white-space:nowrap;
  font-weight:600;border-left:2px solid var(--surface)}
table.heat td.hm small{display:block;font-size:11px;font-weight:500;opacity:.8}
table.heat th.own,table.heat td.own{box-shadow:inset 0 0 0 2px var(--s1)}
table.heat td.none{color:var(--ink-muted);font-weight:400}
.hm.b1{background:var(--d-b1)} .hm.b2{background:var(--d-b2)} .hm.b3{background:var(--d-b3);color:#fff}
.hm.r1{background:var(--d-r1)} .hm.r2{background:var(--d-r2)} .hm.r3{background:var(--d-r3);color:#fff}
.legend i.hm{border:1px solid var(--border);background:var(--d-mid)}
.legend i.hm.b1{background:var(--d-b1)} .legend i.hm.b3{background:var(--d-b3)}
.legend i.hm.r1{background:var(--d-r1)} .legend i.hm.r3{background:var(--d-r3)}
.wide{overflow-x:auto;-webkit-overflow-scrolling:touch}
.wide svg{min-width:760px}
@media(max-width:640px){.duo{grid-template-columns:1fr}}
"""

#: Цвета графиков: ступени синей шкалы для воронки и расходящаяся пара
#: синий ↔ красный с серой серединой для тепловой карты (палитра отчёта).
VARS_LIGHT = ("--f1:#a9e2b6;--f2:#5cc670;--f3:#21a038;--f4:#0f6e27;"
              "--d-mid:#f0efec;--d-b1:#cde2fb;--d-b2:#86b6ef;--d-b3:#256abf;"
              "--d-r1:#fbd9d6;--d-r2:#f2a29e;--d-r3:#c43c3b;")
VARS_DARK = ("--f1:#3a8f50;--f2:#2a7f40;--f3:#1f6e34;--f4:#165c2a;"
             "--d-mid:#383835;--d-b1:#1c3a63;--d-b2:#1c5cab;--d-b3:#3987e5;"
             "--d-r1:#4a2321;--d-r2:#8a3533;--d-r3:#e66767;")


# --- калькулятор на дашборде ------------------------------------------------

#: Что можно посчитать и в каких пределах ползунков: сумма, ₽ и срок, мес.
CALC_KINDS = {
    "Кредиты": {"sum": (50_000, 5_000_000, 500_000, 10_000), "term": (6, 84, 36)},
    "Ипотека": {"sum": (1_000_000, 20_000_000, 5_000_000, 100_000), "term": (12, 360, 240)},
    "Вклады": {"sum": (10_000, 5_000_000, 500_000, 10_000), "term": (1, 36, 12)},
    "Накопительные счета": {"sum": (10_000, 5_000_000, 500_000, 10_000), "term": (1, 36, 12)},
}


def calculator_offers(products: Iterable[Any], *, key_rate: float | None,
                      region_methods: dict[str, str]) -> list[dict[str, Any]]:
    """Лучшая базовая проверенная ставка каждого банка в каждой программе —
    с пределами суммы и срока, ПСК и особыми ставками того же банка.

    Те же правила, что у «Места Сбера»: особые и недоступные в регионе ставки
    в расчёт не идут, но показываются в плюсах и минусах банка.
    """
    from . import conditions, market
    best: dict[tuple[str, str], Any] = {}
    special: dict[tuple[str, str], list[str]] = {}
    for p in products:
        if p.category not in CALC_KINDS:
            continue
        program = market.program_of(p)
        key = (program, p.bank)
        rate = p.rate_max if p.category in market.SAVINGS else p.rate_min
        rate = rate if rate is not None else (p.rate_min or p.rate_max)
        if rate is None:
            continue
        if not conditions.is_comparable(p):
            kind, reason = conditions.kind_of(p)
            special.setdefault(key, []).append(
                f"{conditions.LABELS[kind]}: {pct(rate)} — «{p.title}»")
            continue
        check = market.assess(p, key_rate=key_rate,
                              region_method=market.method_of(p, region_methods))
        if not check.usable:
            continue
        current = best.get(key)
        higher = p.category in market.SAVINGS
        if current is None or (rate > current[1] if higher else rate < current[1]):
            best[key] = (p, rate)
    out = []
    for (program, bank), (p, rate) in best.items():
        out.append({
            "program": program, "kind": p.category, "bank": bank, "title": p.title,
            "url": p.source_url or "", "rate": rate,
            "apr": [p.apr_min, p.apr_max] if p.apr_min is not None else None,
            "sum": [p.amount_min, p.amount_max],
            "term": [p.term_min_months, p.term_max_months],
            "special": special.get((program, bank), [])[:3],
            "calc": (p.terms or {}).get("Калькулятор на сайте", ""),
        })
    out.sort(key=lambda o: (o["kind"], o["program"], o["bank"]))
    return out


def calculator_block(offers: list[dict[str, Any]], *, home: str) -> str:
    """Калькулятор по всем банкам: сумма и срок — полем, кнопками или
    ползунком; результат — таблица банков (платёж, переплата или доход).

    Переделан 03.11.2026 по замечаниям: ползунки на телефоне неудобны и
    сумму нельзя было вписать, карточки перегружены текстом, не было
    платежа в месяц крупно и дохода с капитализацией."""
    import json
    if not offers:
        return ""
    programs: dict[str, str] = {}
    for o in offers:
        programs.setdefault(o["program"], o["kind"])
    # Программы, где банков хотя бы два, — первыми: сравнивать есть с кем.
    counts = {p: sum(1 for o in offers if o["program"] == p) for p in programs}
    first = ("Потребительский кредит", "Рефинансирование", "Новостройки", "Вторичное жильё",
             "Семейная ипотека", "Вклады", "Накопительные счета", "Автокредит")
    order = sorted(programs, key=lambda p: (
        -min(counts[p], 2), first.index(p) if p in first else len(first),
        list(CALC_KINDS).index(programs[p]), p))
    options = "".join(f'<option value="{e(p)}">{e(p)} · {counts[p]} банк.</option>'
                      for p in order)
    data = json.dumps({"offers": offers, "kinds": CALC_KINDS, "presets": CALC_PRESETS,
                       "home": home, "codes": brand.js_codes()}, ensure_ascii=False).replace("</", "<\\/")
    return (_CALC_HTML.replace("__OPTIONS__", options).replace("__DATA__", data))


#: Быстрые кнопки: суммы в рублях, сроки в месяцах.
CALC_PRESETS = {
    "Кредиты": {"sum": [100_000, 300_000, 500_000, 1_000_000, 3_000_000],
                "term": [12, 24, 36, 60, 84]},
    "Ипотека": {"sum": [3_000_000, 5_000_000, 8_000_000, 12_000_000],
                "term": [120, 180, 240, 300, 360]},
    "Вклады": {"sum": [100_000, 500_000, 1_000_000, 3_000_000], "term": [3, 6, 12, 24]},
    "Накопительные счета": {"sum": [100_000, 500_000, 1_000_000, 3_000_000],
                            "term": [3, 6, 12, 24]},
}

_CALC_HTML = """
<div class="calc">
  <div class="calc-ctl">
    <label class="cf cf-prog"><span>Продукт</span><select id="cProg">__OPTIONS__</select></label>
    <div class="cf">
      <span>Сумма, ₽</span>
      <input id="cSumIn" class="cin" inputmode="decimal" autocomplete="off" aria-label="Сумма">
      <div class="chips" id="cSumChips"></div>
      <input id="cSum" type="range" aria-label="Сумма ползунком">
    </div>
    <div class="cf">
      <span>Срок</span>
      <div class="cterm"><input id="cTermIn" class="cin" inputmode="numeric" autocomplete="off"
        aria-label="Срок"><select id="cUnit" aria-label="Единица срока"><option value="12">лет</option>
        <option value="1">мес</option></select></div>
      <div class="chips" id="cTermChips"></div>
      <input id="cTerm" type="range" aria-label="Срок ползунком">
    </div>
  </div>
  <label class="cchk" id="cCapBox"><input type="checkbox" id="cCap" checked>
    проценты каждый месяц добавляются к вкладу (капитализация)</label>
  <p class="calc-sum" id="cHead"></p>
  <div class="scroll"><table class="ctab"><thead id="cThead"></thead><tbody id="cRows"></tbody></table></div>
  <p class="hint" id="cNote"></p>
</div>
<script>
(function(){
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = t => String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const rub = v => Math.round(v).toLocaleString('ru-RU') + ' ₽';
const short = v => v >= 1e6 ? (v / 1e6).toLocaleString('ru-RU') + ' млн' : (v / 1e3).toLocaleString('ru-RU') + ' тыс';
const pc = v => v.toFixed(2).replace('.', ',') + ' %';
const yrs = y => y + ' ' + (y % 10 === 1 && y % 100 !== 11 ? 'год' : [2,3,4].includes(y % 10) && ![12,13,14].includes(y % 100) ? 'года' : 'лет');
const months = m => m % 12 === 0 ? yrs(m / 12) : m + ' мес';
// «1,5 млн», «300 тыс», «2 500 000» → рубли
function parseSum(t) {
  t = String(t).toLowerCase().replace(/\\s|₽|руб\\.?/g, '').replace(',', '.');
  const m = t.match(/^(\\d+(?:\\.\\d+)?)(млн|м|тыс|т|k|к)?$/);
  if (!m) return NaN;
  const mult = {'млн': 1e6, 'м': 1e6, 'тыс': 1e3, 'т': 1e3, 'k': 1e3, 'к': 1e3}[m[2]] || 1;
  return Math.round(parseFloat(m[1]) * mult);
}
let S = 0, N = 0, kind = '';
function kindOf() { return D.offers.find(o => o.program === $('cProg').value).kind; }
function chips(box, values, fmt, pick, current) {
  box.innerHTML = values.map(v => `<button type="button" class="chip${v === current ? ' on' : ''}" data-v="${v}">${fmt(v)}</button>`).join('');
  box.querySelectorAll('button').forEach(b => b.onclick = () => pick(+b.dataset.v));
}
function setup() {
  const k = kindOf();
  if (k !== kind) {
    kind = k; const c = D.kinds[k];
    S = c.sum[2]; N = c.term[2];
    $('cUnit').value = k === 'Ипотека' ? '12' : '1';
  }
  const c = D.kinds[k];
  Object.assign($('cSum'), {min: c.sum[0], max: c.sum[1], step: c.sum[3]});
  Object.assign($('cTerm'), {min: c.term[0], max: c.term[1], step: 1});
  $('cCapBox').style.display = ['Вклады', 'Накопительные счета'].includes(k) ? '' : 'none';
  sync(); draw();
}
function sync() {
  $('cSumIn').value = S.toLocaleString('ru-RU');
  $('cSum').value = S;
  const u = +$('cUnit').value;
  $('cTermIn').value = u === 12 && N % 12 === 0 ? N / 12 : (u === 12 ? (N / 12).toFixed(1).replace('.', ',') : N);
  $('cTerm').value = N;
  const p = D.presets[kind];
  chips($('cSumChips'), p.sum, short, v => { S = v; sync(); draw(); }, S);
  chips($('cTermChips'), p.term, months, v => { N = v; sync(); draw(); }, N);
}
function draw() {
  const prog = $('cProg').value, cap = $('cCap').checked;
  const rows = D.offers.filter(o => o.program === prog).map(o => Object.assign({}, o));
  const save = ['Вклады', 'Накопительные счета'].includes(rows[0].kind);
  for (const o of rows) {
    const r = o.rate / 100 / 12;
    if (save) {
      o.income = cap ? S * (Math.pow(1 + r, N) - 1) : S * o.rate / 100 * N / 12;
      o.end = S + o.income;
    } else {
      o.pay = r ? S * r / (1 - Math.pow(1 + r, -N)) : S / N;
      o.over = o.pay * N - S; o.all = o.pay * N;
    }
    const warn = [];
    if (o.sum[0] && S < o.sum[0]) warn.push('сумма меньше минимума банка — ' + rub(o.sum[0]));
    if (o.sum[1] && S > o.sum[1]) warn.push('сумма больше максимума банка — ' + rub(o.sum[1]));
    if (o.term[0] && N < o.term[0]) warn.push('срок меньше минимального — ' + months(o.term[0]));
    if (o.term[1] && N > o.term[1]) warn.push('срок больше максимального — ' + months(o.term[1]));
    o.warn = warn;
  }
  // Банк, которому сумма или срок не подходят, этот кредит не выдаст:
  // такие — вниз и не «лучшие», даже если ставка ниже.
  rows.sort((a, b) => (a.warn.length > 0) - (b.warn.length > 0)
    || (save ? b.income - a.income : a.over - b.over));
  const fit = rows.filter(o => !o.warn.length);
  const sber = rows.find(o => o.bank === D.home), best = fit[0] || rows[0];
  const val = o => save ? o.income : o.over;
  // заголовок — одна строка: место Сбера и разница с лучшим
  let head;
  if (!sber) head = 'У Сбера в этой программе нет проверенной базовой ставки — сравниваются конкуренты.';
  else if (rows.length === 1) head = 'Сравнить не с кем: в этой программе ставка есть только у Сбера.';
  else if (sber.warn.length) head = 'Сбер такую сумму или срок не выдаёт: ' + sber.warn.join('; ') + '.';
  else {
    const place = fit.indexOf(sber) + 1;
    const of = fit.length + (fit.length < rows.length ? ` (ещё ${rows.length - fit.length} не подходят по сумме или сроку)` : '');
    if (place === 1) head = `Сбер — 1-е место из ${of}` + (save
      ? `: доход ${rub(sber.income)}.` : `: платёж ${rub(sber.pay)}/мес, переплата ${rub(sber.over)}.`);
    else head = `Сбер — ${place}-е место из ${of}. ` + (save
      ? `${best.bank} даёт на ${rub(best.income - sber.income)} больше дохода.`
      : `У ${best.bank} платёж на ${rub(sber.pay - best.pay)}/мес меньше, за срок — на ${rub(sber.over - best.over)}.`);
  }
  $('cHead').textContent = head;
  $('cThead').innerHTML = save
    ? '<tr><th>Банк</th><th class="num">Ставка</th><th class="num">Доход</th><th class="num hide-s">В конце срока</th><th class="num">К Сберу</th></tr>'
    : '<tr><th>Банк</th><th class="num">Ставка</th><th class="num">Платёж/мес</th><th class="num hide-s">Переплата</th><th class="num hide-s">Всего</th><th class="num">К Сберу</th></tr>';
  const cols = save ? 5 : 6;
  $('cRows').innerHTML = rows.map((o, i) => {
    const d = sber && o !== sber ? val(o) - val(sber) : null;
    const better = d !== null && (save ? d > 0 : d < 0);
    const vs = d === null ? (o === sber ? '—' : '') :
      `<span class="${better ? 'up' : 'down'}">${d > 0 ? '+' : '−'}${rub(Math.abs(d))}</span>`;
    const cells = save
      ? `<td class="num"><b>${rub(o.income)}</b></td><td class="num hide-s">${rub(o.end)}</td>`
      : `<td class="num"><b>${rub(o.pay)}</b><span class="sub">перепл. ${rub(o.over)}</span></td><td class="num hide-s">${rub(o.over)}</td><td class="num hide-s">${rub(o.all)}</td>`;
    const info = [];
    for (const w of o.warn) info.push('<span class="con">⚠ ' + esc(w) + '</span>');
    if (o.apr) info.push('<span>ПСК ' + (o.apr[0] === o.apr[1] ? pc(o.apr[0]) : pc(o.apr[0]) + '–' + pc(o.apr[1])) + ' — со страховками и комиссиями дороже ставки</span>');
    for (const s of o.special) info.push('<span>особые условия: ' + esc(s) + '</span>');
    if (o.calc) info.push('<span>калькулятор на сайте банка: ' + esc(o.calc) + '</span>');
    info.push(`<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.title)} — страница банка ↗</a>`);
    const bc = D.codes[o.bank] || 'other';
    return `<tr class="cr${o.bank === D.home ? ' own' : ''}${o.warn.length ? ' nofit' : ''}" data-i="${i}" style="--bc:var(--b-${bc})">
      <td><span class="arr">▸</span> <span class="bn"><i class="bl bl-${bc}"></i><b>${esc(o.bank)}</b></span>${o === best && fit.length > 1 ? ' <span class="star" title="лучший вариант">★</span>' : ''}${o.warn.length ? ' <span class="warn" title="' + esc(o.warn.join('; ')) + '">⚠</span>' : ''}<div class="ct">${esc(o.title)}</div></td>
      <td class="num">${pc(o.rate)}</td>${cells}<td class="num">${vs}</td></tr>
      <tr class="cd" id="cd${i}" hidden><td colspan="${cols}">${info.join('')}</td></tr>`;
  }).join('');
  $('cRows').querySelectorAll('tr.cr').forEach(tr => tr.onclick = () => {
    const det = $('cd' + tr.dataset.i); det.hidden = !det.hidden; tr.classList.toggle('open', !det.hidden); });
  $('cNote').textContent = save
    ? 'По витринной ставке «до», без налога. Нажми на строку — подробности по банку.'
    : 'Аннуитет по витринной ставке «от», без страховок и комиссий — лучший случай. Нажми на строку — подробности.';
}
$('cProg').addEventListener('change', setup);
$('cSum').addEventListener('input', () => { S = +$('cSum').value; sync(); draw(); });
$('cTerm').addEventListener('input', () => { N = +$('cTerm').value; sync(); draw(); });
$('cSumIn').addEventListener('change', () => { const v = parseSum($('cSumIn').value); if (v > 0) S = v; sync(); draw(); });
$('cSumIn').addEventListener('keydown', ev => { if (ev.key === 'Enter') $('cSumIn').blur(); });
$('cTermIn').addEventListener('change', () => {
  const v = parseFloat(String($('cTermIn').value).replace(',', '.'));
  if (v > 0) N = Math.max(1, Math.round(v * +$('cUnit').value)); sync(); draw(); });
$('cTermIn').addEventListener('keydown', ev => { if (ev.key === 'Enter') $('cTermIn').blur(); });
$('cUnit').addEventListener('change', sync);
$('cCap').addEventListener('change', draw);
setup();
})();
</script>"""


CSS += """
.calc{max-width:100%;overflow:hidden}
.calc-ctl{display:grid;grid-template-columns:1fr 1.2fr 1.2fr;gap:16px;margin-bottom:10px}
.cf{display:flex;flex-direction:column;gap:7px;font-size:13px;color:var(--ink-2);min-width:0}
.cf select{width:100%}
.cf select,.cin{font:inherit;font-size:16px;padding:9px 11px;border-radius:9px;
  border:1px solid var(--border);background:var(--surface);color:var(--ink);min-width:0}
.cin{font-variant-numeric:tabular-nums;font-weight:600}
.cterm{display:flex;gap:8px;min-width:0}.cterm .cin{flex:1;width:0}.cterm select{width:84px;flex:none}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font:inherit;font-size:13px;padding:7px 11px;border-radius:999px;cursor:pointer;
  border:1px solid var(--border);background:var(--surface);color:var(--ink-2);min-height:34px}
.chip.on{background:var(--s1);border-color:var(--s1);color:#fff}
.cf input[type=range]{width:100%;accent-color:var(--s1);height:28px}
.cchk{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--ink-2);margin:2px 0 8px}
.cchk input{width:18px;height:18px;accent-color:var(--s1)}
.calc-sum{font-size:15px;font-weight:600;margin:6px 0 10px}
.ctab{width:100%;border-collapse:collapse}
.ctab th{font-size:12px;color:var(--ink-muted);font-weight:500;text-align:left;padding:6px 8px;
  border-bottom:1px solid var(--grid)}
.ctab td{padding:9px 8px;border-bottom:1px solid var(--grid);vertical-align:top;font-size:14px}
.ctab .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ctab tr.cr{cursor:pointer}.ctab tr.cr:hover td{background:var(--wash)}
.ctab tr.cr td:first-child{box-shadow:inset 4px 0 var(--bc)}
.ctab tr.own td{background:color-mix(in srgb,var(--s1) 9%,transparent)}
.ctab .ct{font-size:12px;color:var(--ink-muted);margin-top:2px}
.ctab .arr{display:inline-block;color:var(--ink-muted);transition:transform .15s}
.ctab tr.open .arr{transform:rotate(90deg)}
.ctab .star{color:#d4a017}.ctab .warn{color:var(--st-critical)}
.ctab tr.nofit td{opacity:.55}
.ctab .sub{display:none;font-size:11.5px;color:var(--ink-muted);font-weight:400}
.ctab .up{color:var(--st-good,#1a7f37);font-weight:600}.ctab .down{color:var(--st-critical);font-weight:600}
.ctab tr.cd td{font-size:12.5px;color:var(--ink-2);display:table-cell}
.ctab tr.cd td>*{display:block;margin:2px 0}.ctab tr.cd .con{color:var(--st-critical)}
@media(max-width:640px){.calc-ctl{grid-template-columns:1fr}.ctab .hide-s{display:none}
  .ctab .sub{display:block}.ctab td,.ctab th{padding:8px 4px}.ctab td{font-size:13px}
  .ctab .ct{display:none}}
"""
