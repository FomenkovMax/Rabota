"""XLSX: таблицы с числами (не строками) и диаграмма Excel из того же набора данных."""

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from bankintel.reports import charts
from bankintel.reports.dataset import fmt_dt

RUB = '#,##0.00 "₽"'
HEAD = PatternFill("solid", fgColor="EEEEEA")
LNR = {"confirmed": "подтверждена", "unavailable": "недоступен", "not_confirmed": "не подтверждена", "unknown": "неизвестно"}


def _d(x) -> float | None:
    return None if x is None else float(Decimal(x))


def _sheet(wb, title, header, rows, widths=None, formats=None):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), HEAD
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for col, fmt in (formats or {}).items():
        for cell in ws[col][1:]:
            cell.number_format = fmt
    ws.freeze_panes = "A2"
    return ws


def _neutralise_formulas(wb: Workbook) -> None:
    """Названия продуктов приходят с чужих сайтов: значение «=HYPERLINK(...)» не должно стать формулой.
    Намеренных формул в отчёте нет (диаграммы ссылаются на диапазоны), поэтому все такие ячейки — текст."""
    for ws in wb:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"


def render_xlsx(ds: dict) -> bytes:
    wb = Workbook()
    m = ds["meta"]
    ws = wb.active
    ws.title = "Сводка"
    for row in [
        ["Banking Intelligence AI — конкурентный анализ вкладов и накопительных счетов, ЛНР"],
        ["Набор данных", m["dataset_id"]], ["Сформировано", fmt_dt(m["generated_at"])],
        ["Данные от", fmt_dt(m["data_from"]) + " — " + fmt_dt(m["data_to"])],
        ["Банков с данными", f"{m['banks_with_data']} из {m['banks_total']}"],
        ["Доступность в ЛНР подтверждена", f"{m['lnr_confirmed']} из {m['products_total']}"],
        ["ДЕМО-ПРОТОТИП", "Данных Сбербанка (эталона) нет; решения на основе отчёта принимать нельзя без проверки по источникам."], [],
        ["Главное"], *[[t] for t in ds["insights"]], [], ["Ограничения"], *[[t] for t in ds["limitations"]], [], ["Методика"], *[[t] for t in ds["methodology"]],
    ]:
        ws.append(row)
    ws["A1"].font = Font(bold=True, size=14)
    for r in (9, 9 + len(ds["insights"]) + 2, 9 + len(ds["insights"]) + 2 + len(ds["limitations"]) + 2):
        ws.cell(r, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 90

    _sheet(wb, "Охват", ["Банк", "Эталон", "Статус", "Вклады", "Счета", "Причина", "Последняя загрузка", "Результат загрузки"],
           [[c["name"], "да" if c["is_benchmark"] else "", "есть данные" if c["status"] == "data" else "нет данных", c["deposits"], c["savings"],
             c["reason"] or "", fmt_dt(c["last_fetch"]["at"]) if c["last_fetch"] else "", c["last_fetch"]["outcome"] if c["last_fetch"] else ""] for c in ds["coverage"]],
           [14, 8, 14, 9, 9, 70, 18, 18])

    rows = []
    for s in ds["scenarios"]:
        for group, name in ((s["open"], "для всех"), (s["restricted"], "особые условия")):
            for rank, r in enumerate(group, start=1):
                rows.append([s["label"], float(Decimal(s["amount"])), s["months"], s["days"], name, rank, r["bank"], r["name"], r["rate_text"],
                             _d(r["rate_min"]), _d(r["rate_max"]), r["term_text"], _d(r["income_min"]), _d(r["income_max"]),
                             "; ".join(r["warnings"])])
    _sheet(wb, "Сценарии", ["Сценарий", "Сумма, ₽", "Срок, мес.", "Дней", "Группа", "Место в группе", "Банк", "Продукт", "Ставка (сайт)", "Ставка мин., %",
                            "Ставка макс., %", "Срок продукта", "Доход мин., ₽", "Доход макс., ₽", "Предупреждения"], rows,
           [22, 12, 9, 7, 14, 9, 10, 28, 20, 10, 10, 20, 14, 14, 80], {"B": '#,##0', "M": RUB, "N": RUB})

    _sheet(wb, "Исключено", ["Сценарий", "Банк", "Продукт", "Причина"],
           [[s["label"], e["bank"], e["name"], e["reason"]] for s in ds["scenarios"] for e in s["excluded"]], [22, 10, 30, 70])

    ch_rows = [[fmt_dt(c["detected_at"]), c["bank"], c["product"], {"new": "новый", "removed": "исчез", "changed": "изменён"}[c["type"]],
                {"rate": "ставка/срок/сумма", "conditions": "условия", "info": "прочее"}[c["severity"]], c["text"]] for c in ds["changes"]["items"]]
    _sheet(wb, "Изменения", ["Когда", "Банк", "Продукт", "Тип", "Значимость", "Что изменилось"], ch_rows, [18, 10, 28, 10, 18, 120])
    wb["Изменения"].append([])
    mon = ds["changes"]["monitoring"]
    wb["Изменения"].append([f"Окно {ds['changes']['window_days']} дн.; наблюдение с {fmt_dt(mon['since'])}; сравнений с предыдущим запуском: {mon['comparisons']}"
                            + ("; пока базовая линия (первый сбор)" if not mon["comparisons"] else "")])

    def cat(items, deposit):
        head = ["Банк", "Продукт", "Ставка (сайт)", "Ставка мин., %", "Ставка макс., %", "Базовая ставка макс., %"] + (["Срок"] if deposit else []) + \
               ["Сумма от", "Сумма до", "Валюта", "Особые условия", "Плавающая", "Ограничено по времени", "Расхождения источников", "ЛНР", "Проверено", "Ссылка"]
        out = []
        for p in items:
            out.append([p["bank"], p["name"], p["rate_text"], _d(p["rate_min"]), _d(p["rate_max"]), _d(p["base_rate_max"])] + ([p["term_text"]] if deposit else []) +
                       [_d(p["amount_min"]), _d(p["amount_max"]), p["currency"], "да" if "restricted_audience" in p["flags"] else "", "да" if "floating_rate" in p["flags"] else "",
                        "да" if "limited_time" in p["flags"] else "", "; ".join(p["notes"]), LNR[p["lnr_status"]], fmt_dt(p["checked_at"]), p["product_url"]])
        return head, out

    h, r = cat(ds["catalog"]["deposit"], True)
    _sheet(wb, "Вклады", h, r, [10, 28, 20, 10, 10, 10, 22, 14, 14, 8, 10, 10, 12, 30, 16, 18, 60], {"H": '#,##0.00', "I": '#,##0.00'})
    h, r = cat(ds["catalog"]["savings"], False)
    _sheet(wb, "Счета", h, r, [10, 30, 20, 10, 10, 10, 14, 14, 8, 10, 10, 12, 30, 16, 18, 60])

    _sheet(wb, "Источники", ["ID", "Банк", "Ключ источника", "URL", "Происхождение", "Получен", "SHA-256", "Размер, байт"],
           [[d["document_id"], d["bank"], d["source_key"], d["url"], "автоматически" if d["origin"] == "fetched" else "вручную", fmt_dt(d["fetched_at"]), d["sha256"], d["size_bytes"]] for d in ds["sources"]],
           [7, 10, 16, 70, 14, 18, 66, 12])

    # диаграмма Excel: сценарий 500 000 ₽ / 12 мес. (интервал = невидимая база + видимый отрезок)
    target = next((s for s in ds["scenarios"] if s["months"] == 12 and Decimal(s["amount"]) == 500000), ds["scenarios"][0])
    rows_c = charts.chart_rows(target)
    if rows_c:
        wc = wb.create_sheet("График")
        wc.append(["Продукт", "База (скрыта), ₽", "Интервал дохода, ₽", "Доход мин., ₽", "Доход макс., ₽", "Особые условия"])
        eps = max(r["hi"] for r in rows_c) * Decimal("0.012")
        for r_ in reversed(rows_c):
            lo = r_["lo"] if r_["lo"] is not None and r_["hi"] > r_["lo"] else r_["hi"] - eps
            wc.append([r_["label"], float(lo), float(r_["hi"] - lo), _d(str(r_["lo"])) if r_["lo"] is not None else None, float(r_["hi"]), "да" if r_["restricted"] else ""])
        ch = BarChart()
        ch.type, ch.grouping, ch.overlap = "bar", "stacked", 100
        ch.title = f"Интервал дохода, {target['label']} (тонкая метка — нижняя граница не указана)"
        ch.add_data(Reference(wc, min_col=2, max_col=3, min_row=1, max_row=len(rows_c) + 1), titles_from_data=True)
        ch.set_categories(Reference(wc, min_col=1, min_row=2, max_row=len(rows_c) + 1))
        ch.series[0].graphicalProperties.noFill = True
        ch.series[0].graphicalProperties.line.noFill = True
        ch.series[1].graphicalProperties.solidFill = "EB6834"
        ch.legend = None
        ch.height, ch.width = 11, 26
        wc.add_chart(ch, "H2")
        wc.column_dimensions["A"].width = 44
        for c in "BCDE":
            wc.column_dimensions[c].width = 18
        for row in wc.iter_rows(min_row=2, min_col=2, max_col=5):
            for cell in row:
                cell.number_format = RUB

    wb.properties.title, wb.properties.description = "Банковская конкуренция, ЛНР", f"dataset_id={m['dataset_id']}"
    _neutralise_formulas(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
