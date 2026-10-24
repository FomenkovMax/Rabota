"""Графики отчёта. Цвет закреплён за банком (а не за местом в рейтинге); предложения «не для всех» — штриховка."""

from decimal import Decimal
from html import escape

from bankintel.formatting import money

# Категориальная палитра (слоты 1–5, светлая тема), порядок фиксирован; назначение — по банку.
BANK_COLORS = {"sber": "#2a78d6", "psb": "#eb6834", "vtb": "#1baf7a", "genbank": "#eda100", "cmr": "#e87ba4"}
FALLBACK_COLOR = "#8a8984"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e3e2dd", "#fcfcfb"
FONT = "DejaVu Sans, Liberation Sans, Arial, sans-serif"
MAX_ROWS = 8


def bank_color(slug: str) -> str:
    return BANK_COLORS.get(slug, FALLBACK_COLOR)


def chart_rows(scenario: dict, limit: int = MAX_ROWS) -> list[dict]:
    """Топ продуктов сценария по верхней границе дохода (для всех и с особыми условиями)."""
    rows = [(r, False) for r in scenario["open"]] + [(r, True) for r in scenario["restricted"]]
    rows.sort(key=lambda x: Decimal(x[0]["income_max"]), reverse=True)
    out = []
    for r, restricted in rows[:limit]:
        out.append({
            "label": f"{r['bank']} · {r['name']}", "bank": r["bank"], "slug": r["bank_slug"], "restricted": restricted,
            "lo": Decimal(r["income_min"]) if r["income_min"] is not None else None, "hi": Decimal(r["income_max"]),
            "rate": r["rate_text"] or "",
        })
    return out


def value_label(row: dict) -> str:
    if row["lo"] is not None and row["lo"] == row["hi"]:
        return money(row["hi"])
    return f"{money(row['lo'])} – {money(row['hi'])}" if row["lo"] is not None else f"до {money(row['hi'])}"


def _nice_max(x: Decimal) -> Decimal:
    """Ближайшее сверху «круглое» значение (1, 2, 2.5, 5 × 10^n) для оси."""
    for exp in range(0, 12):
        for step in ("1", "2", "2.5", "5"):
            cand = Decimal(step) * (Decimal(10) ** exp)
            if cand >= x:
                return cand
    return x


def svg_range_chart(rows: list[dict], width: int = 760, uid: str = "c0") -> str:
    """Горизонтальные интервалы дохода. Круг — верхняя граница; штрих — нижняя не указана; штриховка — не для всех."""
    if not rows:
        return ""
    label_w, value_w, row_h, top = 250, 150, 28, 8
    plot_w = width - label_w - value_w - 10
    axis_max = _nice_max(max(r["hi"] for r in rows))
    height = top + row_h * len(rows) + 26
    x = lambda v: label_w + float(v / axis_max) * plot_w  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'role="img" aria-label="Интервалы дохода по продуктам" font-family="{FONT}" font-size="11">']
    slugs = sorted({r["slug"] for r in rows if r["restricted"]})
    out.append("<defs>" + "".join(
        f'<pattern id="{uid}-h-{s}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        f'<rect width="6" height="6" fill="{SURFACE}"/><rect width="3" height="6" fill="{bank_color(s)}"/></pattern>' for s in slugs
    ) + "</defs>")
    for i in range(5):  # сетка и подписи оси
        v = axis_max * i / 4
        gx = x(v)
        out.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" y2="{top + row_h * len(rows)}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{gx:.1f}" y="{height - 8}" text-anchor="middle" fill="{MUTED}">{escape(money(v))}</text>')
    for n, r in enumerate(rows):
        cy = top + n * row_h + row_h / 2
        color = bank_color(r["slug"])
        fill = f"url(#{uid}-h-{r['slug']})" if r["restricted"] else color
        label = r["label"] if len(r["label"]) <= 36 else r["label"][:35] + "…"
        out.append(f'<text x="{label_w - 8}" y="{cy + 4:.1f}" text-anchor="end" fill="{INK}">{escape(label)}</text>')
        if r["lo"] is not None and r["hi"] > r["lo"]:
            x0, x1 = x(r["lo"]), x(r["hi"])
            out.append(f'<rect x="{x0:.1f}" y="{cy - 5:.1f}" width="{x1 - x0:.1f}" height="10" rx="4" fill="{fill}" stroke="{color}" stroke-width="1"/>')
        elif r["lo"] is None:
            out.append(f'<line x1="{x(0):.1f}" y1="{cy:.1f}" x2="{x(r["hi"]):.1f}" y2="{cy:.1f}" stroke="{color}" stroke-width="2" stroke-dasharray="3 3"/>')
        if r["restricted"]:  # полый кружок = предложение не для всех
            out.append(f'<circle cx="{x(r["hi"]):.1f}" cy="{cy:.1f}" r="5" fill="{SURFACE}" stroke="{color}" stroke-width="2"/>')
        else:
            out.append(f'<circle cx="{x(r["hi"]):.1f}" cy="{cy:.1f}" r="5" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>')
        out.append(f'<text x="{width - value_w + 4}" y="{cy + 4:.1f}" fill="{INK2}">{escape(value_label(r))}</text>')
    out.append("</svg>")
    return "".join(out)


def legend_items(rows: list[dict]) -> list[dict]:
    seen, items = set(), []
    for r in rows:
        if r["slug"] not in seen:
            seen.add(r["slug"])
            items.append({"bank": r["bank"], "color": bank_color(r["slug"])})
    return items


def plotly_range_chart(rows: list[dict]):
    """Интерактивная версия того же графика (HTML)."""
    import plotly.graph_objects as go

    fig = go.Figure()
    ordered = list(reversed(rows))  # Plotly рисует снизу вверх
    for slug in dict.fromkeys(r["slug"] for r in rows):
        for restricted in (False, True):
            sub = [r for r in ordered if r["slug"] == slug and r["restricted"] == restricted]
            if not sub:
                continue
            ranged = [r for r in sub if r["lo"] is not None]
            name = sub[0]["bank"] + (" · особые условия" if restricted else "")
            color = bank_color(slug)
            if ranged:
                fig.add_bar(
                    y=[r["label"] for r in ranged], x=[float(r["hi"] - r["lo"]) for r in ranged], base=[float(r["lo"]) for r in ranged],
                    orientation="h", name=name, legendgroup=name, marker=dict(color=color if not restricted else SURFACE,
                        line=dict(color=color, width=1), pattern=dict(shape="/" if restricted else "", fgcolor=color, bgcolor=SURFACE)),
                    width=0.35, customdata=[[value_label(r), r["rate"]] for r in ranged],
                    hovertemplate="<b>%{y}</b><br>Доход: %{customdata[0]}<br>Ставка: %{customdata[1]}<extra></extra>",
                )
            fig.add_scatter(
                y=[r["label"] for r in sub], x=[float(r["hi"]) for r in sub], mode="markers", name=name, legendgroup=name,
                showlegend=not ranged,
                marker=dict(color=SURFACE if restricted else color, size=11, line=dict(color=color if restricted else SURFACE, width=2)),
                customdata=[[value_label(r), r["rate"]] for r in sub],
                hovertemplate="<b>%{y}</b><br>Доход: %{customdata[0]}<br>Ставка: %{customdata[1]}<extra></extra>",
            )
    fig.update_layout(
        height=70 + 34 * len(rows), margin=dict(l=10, r=20, t=10, b=40), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=INK2), separators=", ", barmode="overlay", legend=dict(orientation="h", y=-0.18),
        xaxis=dict(ticksuffix=" ₽", tickformat=",.0f", gridcolor=GRID, zeroline=False, rangemode="tozero"),
        yaxis=dict(automargin=True, showgrid=False, categoryorder="array", categoryarray=[r["label"] for r in ordered]),
    )
    return fig
