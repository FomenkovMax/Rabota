"""Генерация автономного HTML-отчёта.

Отчёт — один файл без внешних зависимостей: открывается двойным кликом,
пересылается почтой, работает без интернета. Это сознательное решение:
адресат отчёта — руководитель, у которого не будет ни Python, ни сервера.

Цветовая логика:
  • светофор использует зарезервированные статусные цвета и всегда идёт
    вместе со значком и подписью — цвет никогда не несёт смысл в одиночку;
  • график истории — две серии (ПСБ / Сбер) с легендой и прямыми подписями;
  • тёмная тема собрана отдельными шагами, а не инверсией.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .compare import GREEN, GREY, LIGHT_LABEL, RED, YELLOW, Comparison

LIGHT_ICON = {GREEN: "▲", YELLOW: "■", RED: "▼", GREY: "—"}
LIGHT_VAR = {GREEN: "--st-good", YELLOW: "--st-warning", RED: "--st-critical", GREY: "--ink-muted"}


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fmt_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",") + "%"


def fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1e6:
        return f"{value / 1e6:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " млн ₽"
    if value >= 1e3:
        return f"{value / 1e3:.0f} тыс ₽"
    return f"{value:.0f} ₽"


def fmt_term(months: int | None) -> str:
    if months is None:
        return "—"
    if months >= 12 and months % 12 == 0:
        return f"{months // 12} лет"
    return f"{months} мес"


def fmt_delta(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}".replace(".", ",") + " п.п."


CSS = """
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb;
  --ink:#0b0b0b; --ink-2:#52514e; --ink-muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834;
  --st-good:#0ca30c; --st-warning:#fab219; --st-critical:#d03b3b;
  --wash:rgba(11,11,11,.035);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --plane:#0d0d0d; --surface:#1a1a19;
    --ink:#fff; --ink-2:#c3c2b7; --ink-muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926;
    --wash:rgba(255,255,255,.05);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19;
  --ink:#fff; --ink-2:#c3c2b7; --ink-muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926;
  --wash:rgba(255,255,255,.05);
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--plane);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:32px 16px 64px;
}
.wrap{max-width:1180px;margin:0 auto}
header{margin-bottom:28px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--ink-2);font-size:14px}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:20px 22px;margin-bottom:20px;
}
h2{font-size:17px;margin:0 0 4px;letter-spacing:-.005em}
.hint{color:var(--ink-muted);font-size:13px;margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.tile .v{font-size:30px;font-weight:650;line-height:1.1;letter-spacing:-.02em}
.tile .k{color:var(--ink-2);font-size:13px;margin-top:4px}
.tile .k b{font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px}
th{
  text-align:left;font-weight:600;color:var(--ink-2);font-size:12.5px;
  text-transform:uppercase;letter-spacing:.04em;
  padding:0 10px 9px;border-bottom:1px solid var(--grid);
}
td{padding:11px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--wash)}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{
  display:inline-flex;align-items:center;gap:6px;white-space:nowrap;
  font-size:12.5px;font-weight:600;padding:3px 9px;border-radius:999px;
  border:1px solid currentColor;
}
.chip .ic{font-size:10px;line-height:1}
.pname{font-weight:600}
.pmeta{color:var(--ink-muted);font-size:12.5px;margin-top:2px}
a{color:var(--s1)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--ink-2);margin:0 0 14px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.chg{border-left:3px solid var(--st-warning);padding:9px 0 9px 14px;margin-bottom:12px}
.chg:last-child{margin-bottom:0}
.chg.high{border-left-color:var(--st-critical)}
.chg .t{font-weight:600;font-size:14px}
.chg .d{color:var(--ink-2);font-size:13px;margin-top:3px}
.bank{font-size:11.5px;font-weight:700;letter-spacing:.05em;color:var(--ink-muted)}
.empty{color:var(--ink-muted);font-size:14px;padding:12px 0}
.note{
  background:var(--wash);border-radius:8px;padding:12px 14px;
  font-size:13px;color:var(--ink-2);margin-top:14px;
}
footer{color:var(--ink-muted);font-size:12.5px;margin-top:28px;line-height:1.7}
svg{display:block;max-width:100%;overflow:visible}
.tg{
  position:fixed;top:14px;right:14px;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;color:var(--ink-2);
  padding:6px 11px;font:inherit;font-size:12.5px;cursor:pointer;
}
@media(max-width:640px){
  body{padding:20px 12px 48px}
  .scroll{overflow-x:auto}
  h1{font-size:21px}
}
"""


def _tiles(counts: dict[str, int], changes: list[Any], total_promos: int) -> str:
    high = sum(1 for c in changes if c["severity"] == "high")
    items = [
        (counts[RED], "Проигрываем ПСБ", "--st-critical"),
        (counts[YELLOW], "Паритет", "--st-warning"),
        (counts[GREEN], "Выигрываем", "--st-good"),
        (counts[GREY], "Нет данных", "--ink-muted"),
        (total_promos, "Акций отслеживается", "--s1"),
        (high, "Важных изменений за неделю", "--s2"),
    ]
    cells = "".join(
        f'<div class="tile"><div class="v" style="color:var({var})">{value}</div>'
        f'<div class="k">{e(label)}</div></div>'
        for value, label, var in items
    )
    return f'<div class="tiles">{cells}</div>'


def _traffic_table(comparisons: list[Comparison]) -> str:
    if not comparisons:
        return ('<p class="empty">Пар для сравнения нет. Заполни config/product_map.yaml '
                'и добавь выгрузку Сбера.</p>')

    rows = []
    for c in comparisons:
        var = LIGHT_VAR[c.light]
        chip = (f'<span class="chip" style="color:var({var})">'
                f'<span class="ic">{LIGHT_ICON[c.light]}</span>{e(LIGHT_LABEL[c.light])}</span>')
        # Показываем ту же границу диапазона, которая сравнивалась:
        # «от» для кредитов, «до» для вкладов.
        prefix = "до " if c.rate_bound == "max" else "от "
        psb_rate = (prefix + fmt_rate(c.psb_rate)) if c.psb_rate is not None else "—"
        sber_rate = (prefix + fmt_rate(c.sber_rate)) if c.sber_rate is not None else "—"
        psb_extra = ""
        if c.psb:
            # Условия, при которых достигается ставка, важнее суммы и срока:
            # «31% на 32 дня до 50 000 ₽» читается иначе, чем просто «31%».
            conditions = getattr(c.psb, "rate_conditions", "")
            detail = conditions or (f"{fmt_money(c.psb.amount_max)} · "
                                    f"{fmt_term(c.psb.term_max_months)}")
            psb_extra = f'<div class="pmeta">{e(detail)}</div>'
        rows.append(
            f"<tr>"
            f'<td><div class="pname">{e(c.label)}</div>'
            f'<div class="pmeta">{e(c.category)}</div></td>'
            f'<td class="num">{e(psb_rate)}{psb_extra}</td>'
            f'<td class="num">{e(sber_rate)}</td>'
            f'<td class="num">{e(fmt_delta(c.delta_rate))}</td>'
            f"<td>{chip}</td>"
            f'<td class="pmeta">{e(c.reason)}</td>'
            f"</tr>"
        )
    return (
        '<div class="scroll"><table><thead><tr>'
        "<th>Продукт</th><th>Ставка ПСБ</th><th>Ставка Сбера</th>"
        "<th>Дельта</th><th>Светофор</th><th>Комментарий</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _delta_chart(comparisons: list[Comparison]) -> str:
    """Горизонтальные столбцы дельты со значением на каждом столбце."""
    data = [c for c in comparisons if c.delta_rate is not None]
    if not data:
        return ""

    data = sorted(data, key=lambda c: c.delta_rate or 0)
    row_h, gap, pad_l, pad_r = 26, 8, 250, 92
    height = len(data) * (row_h + gap) + 34
    width, plot_w = 1080, 1080 - pad_l - pad_r
    span = max(1.0, max(abs(c.delta_rate) for c in data)) * 1.18
    zero_x = pad_l + plot_w / 2
    scale = (plot_w / 2) / span

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Дельта ставок Сбер минус ПСБ по продуктам">'
    ]
    parts.append(f'<line x1="{zero_x}" y1="4" x2="{zero_x}" y2="{height - 26}" '
                 f'stroke="var(--axis)" stroke-width="1"/>')

    for index, c in enumerate(data):
        y = index * (row_h + gap) + 6
        delta = c.delta_rate or 0.0
        bar_w = max(2.0, abs(delta) * scale)
        x = zero_x if delta >= 0 else zero_x - bar_w
        var = LIGHT_VAR[c.light]
        label = e(c.label if len(c.label) <= 34 else c.label[:33] + "…")
        value_x = x + bar_w + 8 if delta >= 0 else x - 8
        anchor = "start" if delta >= 0 else "end"

        parts.append(
            f'<text x="{pad_l - 12}" y="{y + row_h / 2 + 4}" text-anchor="end" '
            f'font-size="12.5" fill="var(--ink-2)">{label}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{bar_w:.1f}" height="{row_h}" rx="4" '
            f'fill="var({var})"><title>{e(c.label)}: {e(fmt_delta(delta))}</title></rect>'
            f'<text x="{value_x:.1f}" y="{y + row_h / 2 + 4}" text-anchor="{anchor}" '
            f'font-size="12" font-weight="600" fill="var(--ink-2)" '
            f'style="font-variant-numeric:tabular-nums">{e(fmt_delta(delta))}</text>'
        )

    parts.append(
        f'<text x="{zero_x - 10}" y="{height - 8}" text-anchor="end" font-size="11.5" '
        f'fill="var(--ink-muted)">← ставка Сбера ниже</text>'
        f'<text x="{zero_x + 10}" y="{height - 8}" font-size="11.5" '
        f'fill="var(--ink-muted)">ставка Сбера выше →</text></svg>'
    )
    return "".join(parts)


def rate_label(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + "%"


def _history_chart(series: dict[str, list[tuple[str, float]]], title: str) -> str:
    """Линейный график истории ставок: две серии, легенда, прямые подписи."""
    usable = {name: points for name, points in series.items() if len(points) >= 2}
    if not usable:
        return ""

    width, height = 1080, 260
    pad_l, pad_r, pad_t, pad_b = 52, 120, 16, 34
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    all_dates = sorted({d for points in usable.values() for d, _ in points})
    all_values = [v for points in usable.values() for _, v in points]
    v_min, v_max = min(all_values), max(all_values)
    if v_max - v_min < 0.5:
        v_min, v_max = v_min - 0.5, v_max + 0.5
    date_index = {d: i for i, d in enumerate(all_dates)}
    step = plot_w / max(1, len(all_dates) - 1)

    def x_of(date: str) -> float:
        return pad_l + date_index[date] * step

    def y_of(value: float) -> float:
        return pad_t + plot_h - (value - v_min) / (v_max - v_min) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(title)}">']

    for tick in range(5):
        value = v_min + (v_max - v_min) * tick / 4
        y = y_of(value)
        # Число форматируем отдельно: замена точки на запятую во всей строке
        # испортила бы координаты SVG.
        label = f"{value:.1f}".replace(".", ",")
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
            f'<text x="{pad_l - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
            f'fill="var(--ink-muted)" style="font-variant-numeric:tabular-nums">'
            f'{label}%</text>'
        )

    colors = ["var(--s1)", "var(--s2)"]
    for index, (name, points) in enumerate(usable.items()):
        color = colors[index % len(colors)]
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x_of(d):.1f},{y_of(v):.1f}"
            for i, (d, v) in enumerate(points)
        )
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        for d, v in points:
            parts.append(
                f'<circle cx="{x_of(d):.1f}" cy="{y_of(v):.1f}" r="4" fill="{color}" '
                f'stroke="var(--surface)" stroke-width="2">'
                f'<title>{e(name)} · {e(d[:10])}: {rate_label(v)}</title></circle>'
            )
        last_date, last_value = points[-1]
        last_label = f"{last_value:.2f}".replace(".", ",")
        parts.append(
            f'<text x="{x_of(last_date) + 12:.1f}" y="{y_of(last_value) + 4:.1f}" '
            f'font-size="12.5" font-weight="600" fill="var(--ink-2)">'
            f'{e(name)} {last_label}%</text>'
        )

    for date in (all_dates[0], all_dates[-1]):
        parts.append(
            f'<text x="{x_of(date):.1f}" y="{height - 10}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)">{e(date[:10])}</text>'
        )
    parts.append("</svg>")

    legend = "".join(
        f'<span><i style="background:{colors[i % len(colors)]}"></i>{e(name)}</span>'
        for i, name in enumerate(usable)
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _changes_block(changes: list[Any]) -> str:
    from .changes import KIND_LABEL

    if not changes:
        return '<p class="empty">За неделю изменений не зафиксировано.</p>'

    order = {"high": 0, "medium": 1, "info": 2}
    ranked = sorted(changes, key=lambda c: order.get(c["severity"], 3))[:30]

    blocks = []
    for c in ranked:
        cls = "chg high" if c["severity"] == "high" else "chg"
        detail = ""
        if c["kind"] == "rate" and c.get("delta") is not None:
            arrow = "вырос" if c["delta"] > 0 else "снижен"
            amount = f"{abs(c['delta']):.2f}".replace(".", ",")
            detail = (f"Ставка {arrow} на {amount} п.п.: "
                      f"{c['old_value']} → {c['new_value']}")
        elif c["kind"] in ("promo_new", "promo_gone"):
            detail = c.get("new_value") or c.get("old_value") or ""
        elif c["kind"] == "terms":
            detail = f"«{c['field']}»: {c['old_value'][:140]} → {c['new_value'][:140]}"
        blocks.append(
            f'<div class="{cls}"><div class="t">'
            f'<span class="bank">{e(c["bank"])}</span> · '
            f'{e(KIND_LABEL.get(c["kind"], c["kind"]))} — {e(c["title"][:120])}</div>'
            f'<div class="d">{e(detail)}</div></div>'
        )
    tail = (f'<p class="hint" style="margin-top:14px">Показаны 30 из {len(changes)} изменений.</p>'
            if len(changes) > 30 else "")
    return "".join(blocks) + tail


def _promo_fields(item: Any) -> tuple[str, str, str]:
    """Достаёт (title, text, url) и из строки БД, и из объекта Promo."""
    if hasattr(item, "keys"):
        return (item["title"] or "", item["text"] or "", item["url"] or "")
    return (getattr(item, "title", ""), getattr(item, "text", ""),
            getattr(item, "url", ""))


_OFFER_NUMBER_RE = re.compile(r"\d+\s*%|\d[\d\s]*\s*₽|\d+\s*(?:дн|мес|год)")


def _promos_table(promos_psb: list[Any], promos_sber: list[Any]) -> str:
    """Акции обоих банков.

    Предложения с конкретными цифрами идут первыми: «кешбэк 30%» руководителю
    полезнее, чем «лучшая карта года», а листать шестьдесят строк ради
    содержательных он не станет.
    """
    entries: list[tuple[int, str, str, str, str]] = []
    for bank, items in (("ПСБ", promos_psb), ("Сбер", promos_sber)):
        for item in items:
            title, text, url = _promo_fields(item)
            if not title:
                continue
            concrete = 0 if _OFFER_NUMBER_RE.search(f"{title} {text}") else 1
            entries.append((concrete, bank, title, text, url))

    if not entries:
        return '<p class="empty">Действующих акций не обнаружено.</p>'

    entries.sort(key=lambda row: (row[0], row[1], row[2]))

    rows = []
    for _, bank, title, text, url in entries:
        link = (f' <a href="{e(url)}" target="_blank" rel="noopener">источник</a>'
                if url else "")
        rows.append(
            f'<tr><td><span class="bank">{e(bank)}</span></td>'
            f'<td><div class="pname">{e(title[:160])}</div>'
            f'<div class="pmeta">{e(text[:220])}{link}</div></td></tr>'
        )

    concrete_count = sum(1 for row in entries if row[0] == 0)
    note = (f'<p class="hint" style="margin-top:14px">Всего предложений: {len(entries)}, '
            f'из них с конкретными условиями: {concrete_count}. '
            "Предложения с цифрами показаны первыми.</p>")
    return ('<div class="scroll"><table><thead><tr><th>Банк</th><th>Предложение</th>'
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>" + note)


def render_report(
    *,
    comparisons: list[Comparison],
    counts: dict[str, int],
    changes: list[Any],
    promos_psb: list[Any],
    promos_sber: list[Any],
    history: dict[str, list[tuple[str, float]]],
    region: str,
    generated_at: str,
    run_count: int,
    psb_total: int,
    sber_total: int,
    thresholds: Any,
) -> str:
    total_promos = len(promos_psb) + len(promos_sber)
    delta_chart = _delta_chart(comparisons)
    history_chart = _history_chart(history, "История ставок за год")

    delta_section = ""
    if delta_chart:
        delta_section = (
            '<section class="card"><h2>Дельта ставок по продуктам</h2>'
            '<p class="hint">Ставка Сбера минус ставка ПСБ. Цвет столбца повторяет '
            "светофор, значение подписано на каждом столбце.</p>"
            f"{delta_chart}</section>"
        )

    history_section = ""
    if history_chart:
        history_section = (
            '<section class="card"><h2>История ставок</h2>'
            '<p class="hint">Средняя витринная ставка по сопоставленным продуктам, '
            "по неделям сбора: «от» для кредитных продуктов, «до» для сберегательных. "
            "Глубина хранения — один календарный год.</p>"
            f"{history_chart}</section>"
        )

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ПСБ vs Сбер — {e(region)}</title>
<style>{CSS}</style></head>
<body>
<button class="tg" onclick="var r=document.documentElement;
  r.dataset.theme = r.dataset.theme==='dark' ? 'light' : 'dark';">Тема</button>
<div class="wrap">
<header>
  <h1>Сравнение розничных продуктов: ПСБ и Сбер</h1>
  <div class="sub">Регион: <b>{e(region)}</b> · Отчёт сформирован {e(generated_at)} ·
  Собрано продуктов: ПСБ {psb_total}, Сбер {sber_total} · Запусков в истории: {run_count}</div>
</header>

{_tiles(counts, changes, total_promos)}

<section class="card">
  <h2>Светофор по идентичным продуктам</h2>
  <p class="hint">Сравниваются только пары, подтверждённые вручную в product_map.yaml.
  Пороги: паритет до {str(thresholds.parity).replace(".", ",")} п.п.,
  проигрыш от {str(thresholds.loss).replace(".", ",")} п.п.
  Для вкладов и накопительных счетов выгодой клиента считается ставка выше, для кредитов — ниже.</p>
  {_traffic_table(comparisons)}
</section>

{delta_section}

<section class="card">
  <h2>Изменения за неделю</h2>
  <p class="hint">Сопоставление с предыдущим успешным сбором.</p>
  {_changes_block(changes)}
</section>

{history_section}

<section class="card">
  <h2>Действующие акции</h2>
  <p class="hint">По ПСБ — собраны с сайта автоматически. По Сберу — из предоставленной выгрузки.</p>
  {_promos_table(promos_psb, promos_sber)}
</section>

<footer>
  Источник данных ПСБ — публичные страницы psbank.ru, раздел «Частным лицам»,
  регион запроса «{e(region)}». Источник данных Сбера — предоставленная выгрузка.<br>
  Ставки указаны как минимальные заявленные и носят справочный характер:
  фактическая ставка определяется индивидуально. Перед использованием
  в управленческих решениях сверьтесь с первоисточником по ссылке в строке продукта.
</footer>
</div></body></html>"""


def write_report(path: str | Path, html_text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path
