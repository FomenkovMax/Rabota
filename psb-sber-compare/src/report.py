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
.seg{margin-bottom:26px;padding-bottom:20px;border-bottom:1px solid var(--grid)}
.segcount{color:var(--ink-muted);font-size:12.5px;margin-left:auto}
.vs{
  display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center;
  background:var(--wash);border-radius:10px;padding:14px 16px;margin-bottom:10px;
}
.vs-side{min-width:0}
.vs-bank{font-size:11.5px;font-weight:700;letter-spacing:.05em;color:var(--ink-muted)}
.vs-val{font-size:23px;font-weight:650;line-height:1.2;margin:2px 0 3px;letter-spacing:-.01em}
.vs-none{font-size:15px;font-weight:600;color:var(--ink-muted)}
.vs-name{font-size:12.5px;color:var(--ink-2);overflow-wrap:anywhere}
.vs-mid{font-size:12px;color:var(--ink-muted);white-space:nowrap}
.segdet{margin-top:4px}
.segdet summary{
  cursor:pointer;font-size:13px;color:var(--ink-2);
  padding:6px 0;user-select:none;
}
.segdet summary:hover{color:var(--ink)}
.segdet[open] summary{margin-bottom:6px}
.seg:last-of-type{margin-bottom:8px}
.seghead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:2px}
.seghead h3{font-size:15px;margin:0;letter-spacing:-.005em}
.seghint{color:var(--ink-muted);font-size:13px;margin:0 0 6px}
.segsrc{color:var(--ink-muted);font-size:12.5px;margin:0 0 10px;font-style:italic}
.exp{margin:8px 0 0;padding-left:18px}
.exp li{margin-bottom:4px}
.cat{border-bottom:1px solid var(--grid)}
.cat:last-of-type{border-bottom:0}
.cat>summary{
  cursor:pointer;display:flex;align-items:center;gap:10px;
  padding:12px 0;font-weight:600;font-size:15px;list-style:none;user-select:none;
}
.cat>summary::-webkit-details-marker{display:none}
.cat>summary::before{content:"▸";color:var(--ink-muted);font-size:12px;transition:transform .15s}
.cat[open]>summary::before{transform:rotate(90deg)}
.cat .cnt{color:var(--ink-muted);font-size:12.5px;font-weight:500;margin-left:auto}
.catgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;padding:0 0 16px}
.catcol h4{
  margin:0 0 4px;font-size:11.5px;font-weight:700;letter-spacing:.05em;
  color:var(--ink-muted);text-transform:uppercase;
}
.catrow{
  display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  padding:7px 0;border-bottom:1px dashed var(--grid);font-size:13.5px;
}
.catrow:last-child{border-bottom:0}
.catrow .n{min-width:0;overflow-wrap:anywhere}
.catrow .n a{color:var(--ink);text-decoration:none}
.catrow .n a:hover{text-decoration:underline}
.catrow .src{display:block;color:var(--ink-muted);font-size:11.5px}
.catrow .r{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600}
.catrow .r.none{color:var(--ink-muted);font-weight:500}
@media(max-width:640px){
  .vs{grid-template-columns:1fr;gap:10px;text-align:left}
  .vs-mid{justify-self:start}
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
        (total_promos, "Действующих акций", "--s1"),
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
            # Саму ставку из условий убираем: она уже стоит в соседней
            # колонке, и повтор «до 13,80% | 13,80% — 181 день» только шумит.
            conditions = re.sub(r"^\d+[,.]\d+%\s*[—-]\s*", "",
                                getattr(c.psb, "rate_conditions", ""))
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


VERDICT_VAR = {"green": "--st-good", "yellow": "--st-warning",
               "red": "--st-critical", "grey": "--ink-muted"}
VERDICT_ICON = {"green": "▲", "yellow": "■", "red": "▼", "grey": "—"}
VERDICT_LABEL = {"green": "Выигрываем", "yellow": "Паритет",
                 "red": "Проигрываем", "grey": "Не сравнить"}


def _promo_rows(promos: list[Any], bank: str) -> str:
    """Строки одного банка внутри сегмента."""
    if not promos:
        return (f'<tr><td class="bank">{e(bank)}</td>'
                f'<td colspan="3" class="empty" style="padding:8px 10px">'
                "Предложений нет</td></tr>")

    # Гарантированная выгода сверху, розыгрыши — в конце сегмента.
    from .promos import sort_key

    ordered = sorted(promos, key=sort_key)
    rows = []
    for promo in ordered:
        link = (f' <a href="{e(promo.url)}" target="_blank" rel="noopener">источник</a>'
                if promo.url else "")
        rows.append(
            f'<tr><td class="bank">{e(bank)}</td>'
            f'<td><div class="pname">{e(promo.title[:130])}</div>'
            f'<div class="pmeta">{e(promo.text[:150])}{link}</div></td>'
            f'<td class="num"><b>{e(promo.benefit_display)}</b>'
            f'<div class="pmeta">{e(promo.benefit_label)}</div></td>'
            f'<td class="pmeta">{e(promo.valid_display)}</td></tr>'
        )
    return "".join(rows)


def _best_offer(promos: list[Any], item: Any) -> Any | None:
    """Сильнейшее предложение банка — в тех же единицах, что и вердикт."""
    from .promos import best_offer

    return best_offer(promos, getattr(item, "best_type", ""),
                      getattr(item, "best_unit", ""))


def _versus(item: Any) -> str:
    """Шапка сегмента: лучшее у ПСБ против лучшего у Сбера, крупно.

    Руководителю нужен ответ за секунду, а не чтение таблицы на двадцать
    строк. Подробности — ниже, в таблице.
    """
    psb, sber = _best_offer(item.psb, item), _best_offer(item.sber, item)
    var = VERDICT_VAR.get(item.verdict, "--ink-muted")
    use_products = getattr(item, "basis", "") == "витрина продуктов"

    def side(promo: Any, bank: str, highlight: bool, product: Any = None) -> str:
        head = f'<div class="vs-bank">{e(bank)}</div>'

        # Когда вывод опирается на витрину, показываем продукт, а не пустоту:
        # «нет акций» рядом с банком, у которого вклады под 31%, — обман.
        if (use_products or promo is None) and product is not None and product.rate is not None:
            color = f"var({var})" if highlight else "var(--ink)"
            return (f'<div class="vs-side">{head}'
                    f'<div class="vs-val" style="color:{color}">{e(product.display)}</div>'
                    f'<div class="vs-name">{e(product.title[:70])}</div></div>')

        if promo is None:
            return (f'<div class="vs-side">{head}'
                    '<div class="vs-val vs-none">акций не найдено</div>'
                    '<div class="vs-name">—</div></div>')

        # Крупной цифрой показываем только измеримую выгоду. «Прочее»
        # набранное в 23 пункта выглядит как результат, хотя это признание
        # в том, что величину извлечь не удалось.
        if promo.benefit_value is None:
            return (f'<div class="vs-side">{head}'
                    f'<div class="vs-val vs-none">{e(promo.benefit_label)}</div>'
                    f'<div class="vs-name">{e(promo.title[:70])}</div></div>')

        color = f"var({var})" if highlight else "var(--ink)"
        return (f'<div class="vs-side">{head}'
                f'<div class="vs-val" style="color:{color}">{e(promo.benefit_display)}</div>'
                f'<div class="vs-name">{e(promo.title[:70])}</div></div>')

    # Подсвечиваем того, кто сильнее: при «выигрываем» — Сбера, иначе ПСБ.
    psb_strong = item.verdict == "red"
    sber_strong = item.verdict == "green"
    return (f'<div class="vs">'
            f'{side(psb, "ПСБ", psb_strong, item.psb_product)}'
            f'<div class="vs-mid">против</div>'
            f'{side(sber, "Сбер", sber_strong, item.sber_product)}</div>')


def _showcase_line(item: Any) -> str:
    """Витрина продуктов сегмента — когда вывод опирается на неё."""
    if getattr(item, "basis", "") != "витрина продуктов":
        return ""
    psb, sber = item.psb_product, item.sber_product
    if psb is None or sber is None:
        return ""
    return ('<p class="segsrc">Вывод построен по условиям продуктов: '
            f'ПСБ — {e(psb.title[:60])}, Сбер — {e(sber.title[:60])}</p>')


def _promo_analysis(segments: list[Any], expired: list[Any]) -> str:
    """Сравнительный анализ акций по сегментам."""
    if not segments:
        return ('<p class="empty">Действующих предложений не обнаружено.</p>')

    blocks = []
    for item in segments:
        var = VERDICT_VAR.get(item.verdict, "--ink-muted")
        chip = (f'<span class="chip" style="color:var({var})">'
                f'<span class="ic">{VERDICT_ICON.get(item.verdict, "—")}</span>'
                f'{e(VERDICT_LABEL.get(item.verdict, ""))}</span>')
        blocks.append(
            f'<div class="seg">'
            f'<div class="seghead"><h3>{e(item.segment)}</h3>{chip}'
            f'<span class="segcount">ПСБ {len(item.psb)} · Сбер {len(item.sber)}</span></div>'
            f'<p class="seghint">{e(item.headline)}</p>'
            + _showcase_line(item)
            + _versus(item) +
            '<details class="segdet"><summary>Все предложения сегмента</summary>'
            '<div class="scroll"><table><thead><tr>'
            "<th>Банк</th><th>Предложение</th><th>Выгода</th><th>Действует до</th>"
            "</tr></thead><tbody>"
            + _promo_rows(item.psb, "ПСБ")
            + _promo_rows(item.sber, "Сбер")
            + "</tbody></table></div></details></div>"
        )

    # Список завершившихся акций в отчёт не выводим: прошлогодние условия
    # решений не меняют. Они по-прежнему отсеиваются, а их число видно
    # в логе запуска и в базе.
    return "".join(blocks)


_CATEGORY_ORDER = ("Вклады", "Накопительные счета", "Кредиты", "Ипотека",
                   "Кредитные карты", "Дебетовые карты", "Банковские карты")


def _catalog_rate(product: Any) -> tuple[str, bool]:
    """Ставка для каталога и признак того, что это именно ставка."""
    low = product.rate_min
    if low is not None:
        high = product.rate_max if product.rate_max is not None else low
        if low == high:
            return fmt_rate(low), True
        return f"{fmt_rate(low)[:-1]}–{fmt_rate(high)}", True
    if product.apr_min is not None:
        return f"ПСК {fmt_rate(product.apr_min)}", False
    return "не указана", False


def _catalog(catalog: dict[str, list[Any]], banks: list[str]) -> str:
    """Все продукты банков по категориям — и те, у кого нет пары для светофора."""
    def category_of(product: Any) -> str:
        return product.category or "Прочее"

    categories = {category_of(p) for items in catalog.values() for p in items}
    if not categories:
        return '<p class="empty">Продуктов нет: полный сбор по банкам ещё не запускался.</p>'

    def rank(category: str) -> tuple[int, str]:
        known = _CATEGORY_ORDER.index(category) if category in _CATEGORY_ORDER else 99
        return known, category

    blocks = []
    for category in sorted(categories, key=rank):
        columns, counts = [], []
        for bank in banks:
            items = sorted((p for p in catalog.get(bank, []) if category_of(p) == category),
                           key=lambda p: p.title.lower())
            counts.append(f"{bank} {len(items)}")
            rows = []
            for product in items:
                rate, is_rate = _catalog_rate(product)
                terms = product.terms or {}
                source = ("ставка с карточки на витрине раздела"
                          if terms.get("Источник ставки") else "")
                name = (f'<a href="{e(product.source_url)}" target="_blank" rel="noopener">'
                        f'{e(product.title)}</a>' if product.source_url else e(product.title))
                rows.append(
                    f'<div class="catrow"><span class="n">{name}'
                    + (f'<span class="src">{e(source)}</span>' if source else "")
                    + f'</span><span class="r{"" if is_rate else " none"}">{e(rate)}</span></div>')
            body = "".join(rows) or '<p class="empty">В этой категории продуктов не найдено</p>'
            columns.append(f'<div class="catcol"><h4>{e(bank)}</h4>{body}</div>')
        blocks.append(
            f'<details class="cat"><summary>{e(category)}'
            f'<span class="cnt">{e(" · ".join(counts))}</span></summary>'
            f'<div class="catgrid">{"".join(columns)}</div></details>')
    return "".join(blocks)


def render_report(
    *,
    comparisons: list[Comparison],
    counts: dict[str, int],
    changes: list[Any],
    promo_segments: list[Any],
    expired_promos: list[Any],
    promo_active_total: int,
    history: dict[str, list[tuple[str, float]]],
    region: str,
    generated_at: str,
    run_count: int,
    psb_total: int,
    sber_total: int,
    thresholds: Any,
    catalog: dict[str, list[Any]] | None = None,
    catalog_banks: list[str] | None = None,
) -> str:
    total_promos = promo_active_total
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

<section class="card">
  <h2>Каталог продуктов</h2>
  <p class="hint">Все розничные продукты, найденные на сайтах банков, — в том числе те,
  для которых пара в светофоре не настроена. Нажмите на категорию, чтобы раскрыть.
  «Не указана» — на странице продукта ставки нет, цифру мы не додумываем.
  «ПСК» — указана только полная стоимость кредита, она не равна ставке.
  Название ведёт на страницу-источник.</p>
  {_catalog(catalog or {}, catalog_banks or list((catalog or {}).keys()))}
</section>

{delta_section}

<section class="card">
  <h2>Изменения за неделю</h2>
  <p class="hint">Сопоставление с предыдущим успешным сбором.</p>
  {_changes_block(changes)}
</section>

{history_section}

<section class="card">
  <h2>Акции: сравнительный анализ по сегментам</h2>
  <p class="hint">Только действующие предложения — завершившиеся отсеяны.
  Внутри сегмента сравнивается однотипная выгода: кешбэк с кешбэком, ставка со ставкой.
  Если размеченных акций у банка нет, вывод строится по условиям его продуктов —
  отсутствие промо-баннера не означает отсутствие продукта.
  Данные собраны с публичных сайтов банков.</p>
  {_promo_analysis(promo_segments, expired_promos)}
</section>

<footer>
  Источники — публичные страницы банков, раздел для частных лиц,
  регион запроса «{e(region)}».<br>
  Если у банка в строке продукта указано «регион на сайте не выбран»,
  условия собраны те, которые сайт отдал по умолчанию, — как правило,
  московские. Сравнивать их с луганскими напрямую нельзя.<br>
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
