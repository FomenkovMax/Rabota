from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from bankintel.formatting import money, pct
from bankintel.reports import charts
from bankintel.reports.dataset import fmt_date, fmt_dt

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html", "j2"]), trim_blocks=True, lstrip_blocks=True
)
_env.filters.update(money=money, pct=pct, dt=fmt_dt, date=fmt_date)


def _render(ds: dict, mode: str, chart_fn, extra_head: str = "") -> str:
    scenario_charts = []
    for i, s in enumerate(ds["scenarios"]):
        rows = charts.chart_rows(s)
        scenario_charts.append({"rows": rows, "legend": charts.legend_items(rows), "html": chart_fn(rows, f"c{i}") if rows else ""})
    html = _env.get_template("report.html.j2").render(ds=ds, mode=mode, charts=scenario_charts)
    return html.replace("</head>", extra_head + "</head>", 1) if extra_head else html


def render_html(ds: dict) -> str:
    """Самодостаточный HTML: Plotly встроен (работает без интернета)."""
    from plotly.offline import get_plotlyjs

    def chart(rows, uid):
        return charts.plotly_range_chart(rows).to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True})

    return _render(ds, "html", chart, extra_head=f"<script>{get_plotlyjs()}</script>")


def _make_deny_fetcher():
    from weasyprint.urls import URLFetcher, URLFetchingError

    class DenyFetcher(URLFetcher):
        """Отчёт самодостаточен: внешних ресурсов (сеть, file://) в нём быть не должно. Защита «в глубину» на случай,
        если недоверенный текст из чужого HTML когда-нибудь попадёт в разметку неэкранированным."""

        attempted: list[str] = []

        def fetch(self, url, headers=None):
            DenyFetcher.attempted.append(url)
            raise URLFetchingError(f"загрузка внешних ресурсов в отчёте запрещена: {url[:80]}")

    return DenyFetcher


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, url_fetcher=_make_deny_fetcher()()).write_pdf()


def render_pdf(ds: dict) -> bytes:
    return html_to_pdf(_render(ds, "pdf", lambda rows, uid: charts.svg_range_chart(rows, uid=uid)))
