"""Excel-выгрузки: карточки организаций (/inn, пакетная проверка)."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..enrichment.base import LookupResult

STATUS_RU = {"found": "Найдено", "needs_review": "Требует проверки", "not_found": "Не найдено",
             "error": "Ошибка", "disabled": "Обогащение выключено"}
COLS = [("Запрос", None), ("Статус", None), ("ИНН", "inn"), ("ОГРН", "ogrn"), ("Наименование", "name_full"),
        ("ОКВЭД", "okved"), ("Адрес", "address"), ("Руководитель (ЛПР)", "director"), ("Должность", "director_post"),
        ("Учредители", "founders"), ("Числ. (среднесписочная)", "employees"), ("Статус орг.", "status"),
        ("Телефоны", "phones"), ("Email", "emails"), ("Примечание", None)]
NA = "н/д"


def _val(v):
    if v in (None, "", []):
        return NA
    return "; ".join(v) if isinstance(v, list) else v


def _style(ws, widths):
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="21A038")     # зелёный Сбера
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def cards_workbook(items: list[tuple[str, LookupResult]]) -> bytes:
    """items: [(исходный запрос, результат)] -> .xlsx в байтах. Лист 2 — кандидаты для «Требует проверки»."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Карточки"
    ws.append([c[0] for c in COLS])
    review = []
    for query, res in items:
        card = res.card.to_dict() if res.card else {}
        row = [query, STATUS_RU.get(res.status, res.status)]
        row += [_val(card.get(k)) if k else "" for _, k in COLS[2:-1]]
        row.append(res.message or "")
        ws.append(row)
        for i, cand in enumerate(res.candidates, 1):
            review.append([query, i, cand.inn or NA, cand.name_full or NA, cand.address or NA, cand.director or NA])
    _style(ws, [16, 18, 14, 16, 40, 10, 40, 28, 22, 30, 14, 14, 22, 26, 36])
    if review:
        w2 = wb.create_sheet("Требует проверки (топ-3)")
        w2.append(["Запрос", "№", "ИНН", "Наименование", "Адрес", "Руководитель"])
        for r in review:
            w2.append(r)
        _style(w2, [28, 5, 14, 44, 44, 28])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


EV_COLS = ["Оценка", "Категория", "Заголовок", "Суть", "Организация", "ИНН", "Район", "ЛПР", "Численность",
           "≈ ФОТ в год, ₽", "≈ Потенциал в год, ₽", "Возможность для Сбера", "Источники"]


def district_of(ev: dict, channel_districts: dict[str, str] | None = None) -> str:
    """Район: из текста (region организации) или из района канала-источника. Иначе «н/д»."""
    for o in ev.get("organizations") or []:
        if o.get("region"):
            return o["region"]
    for ch in ev.get("channels") or []:
        if (channel_districts or {}).get(ch):
            return channel_districts[ch]
    return NA


def events_workbook(events: list[dict], channel_districts: dict[str, str] | None = None) -> bytes:
    """Excel-выгрузка событий запуска + лист «Формула» с допущениями оценки."""
    from ..finance import FORMULA
    from ..llm.schemas import CATEGORIES
    wb = Workbook()
    ws = wb.active
    ws.title = "События"
    ws.append(EV_COLS)
    for ev in sorted(events, key=lambda e: -e["relevance_score"]):
        enr = ev.get("enriched") or {}
        card = enr.get("card") if enr.get("status") == "found" else None
        org = (ev.get("organizations") or [{}])[0]
        fin = ev.get("finance") or {}
        inn = (card or {}).get("inn") or org.get("inn_if_in_text") or ("требует проверки" if enr.get("status") == "needs_review" else None)
        persons = ev.get("persons") or []
        lpr = (card or {}).get("director") or (persons[0]["name"] if persons else None)
        ws.append([ev["relevance_score"], f"{CATEGORIES[ev['category']][0]} {CATEGORIES[ev['category']][1]}", ev["title"],
                   ev["summary"], _val(org.get("name")), _val(inn), district_of(ev, channel_districts), _val(lpr),
                   _val(fin.get("employees")), _val(round(fin["fot_year"]) if fin.get("fot_year") else None),
                   _val(round(fin["potential_year"]) if fin.get("potential_year") else None),
                   _val(ev.get("business_opportunity")), "\n".join(ev.get("source_urls") or [])])
    _style(ws, [8, 30, 40, 60, 32, 16, 18, 28, 12, 16, 18, 40, 40])
    ws.auto_filter.ref = ws.dimensions
    f = wb.create_sheet("Формула")
    f.append(["Как считается ≈ оценка"])
    f.append([FORMULA])
    f.column_dimensions["A"].width = 120
    f["A2"].alignment = Alignment(wrap_text=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
