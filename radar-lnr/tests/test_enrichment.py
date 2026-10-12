import io

import httpx
import openpyxl
import pytest

from radar.bot.inn_file import MAX_INNS, parse_inn_file
from radar.db import DB
from radar.enrichment.base import AdapterError, LookupResult, OrgCard
from radar.enrichment.dadata import DaDataAdapter, parse_party
from radar.enrichment.service import Enricher
from radar.report.excel import cards_workbook

SBER = "7707083893"
GAZPROM = "7736050003"

PARTY = {"value": 'ООО "Ромашка"', "data": {
    "inn": SBER, "ogrn": "1027700132195", "kpp": "773601001", "okved": "64.19", "employee_count": 250,
    "name": {"full_with_opf": 'Общество с ограниченной ответственностью "Ромашка"', "short_with_opf": 'ООО "Ромашка"'},
    "address": {"value": "г Луганск, ул Ленина, д 1"}, "management": {"name": "Иванов Иван Иванович", "post": "Директор"},
    "state": {"status": "ACTIVE"}, "founders": [{"name": "ООО Холдинг"}],
    "phones": [{"value": "+7 642 000-00-00"}], "emails": [{"value": "info@romashka.example"}], "branch_type": "MAIN"}}


def adapter(handler):
    return DaDataAdapter("k", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_parse_party_maps_fields_and_leaves_missing_empty():
    c = parse_party(PARTY)
    assert c.inn == SBER and c.director == "Иванов Иван Иванович" and c.employees == 250 and c.status == "Действует"
    bare = parse_party({"value": "X", "data": {"inn": GAZPROM}})
    assert bare.director is None and bare.employees is None and bare.founders == []   # ничего не выдумываем


async def test_lookup_inn_found_and_cached(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"suggestions": [PARTY]})

    enr = Enricher(DB(tmp_path / "t.db"), [adapter(handler)])
    r1 = await enr.lookup_inn(SBER)
    r2 = await enr.lookup_inn(SBER)
    assert r1.status == "found" and r1.card.name_short == 'ООО "Ромашка"' and r2.status == "found"
    assert len(calls) == 1                         # второй раз — из кэша


async def test_bad_inn_checksum_rejected_without_api_call(tmp_path):
    enr = Enricher(DB(tmp_path / "t.db"), [adapter(lambda r: pytest.fail("не должно быть запроса"))])
    assert (await enr.lookup_inn("7707083894")).status == "error"


async def test_not_found_and_api_errors(tmp_path):
    enr = Enricher(DB(tmp_path / "t.db"), [adapter(lambda r: httpx.Response(200, json={"suggestions": []}))])
    assert (await enr.lookup_inn(SBER)).status == "not_found"
    bad = Enricher(DB(tmp_path / "t2.db"), [adapter(lambda r: httpx.Response(403))])
    res = await bad.lookup_inn(SBER)
    assert res.status == "error" and "DADATA_API_KEY" in res.message


async def test_name_multiple_candidates_needs_review_top3(tmp_path):
    items = [{"value": f"ООО Ромашка {i}", "data": {"inn": SBER, "name": {"full_with_opf": f"ООО Ромашка {i}"}}} for i in range(5)]
    enr = Enricher(DB(tmp_path / "t.db"), [adapter(lambda r: httpx.Response(200, json={"suggestions": items}))])
    res = await enr.lookup_name("Ромашка")
    assert res.status == "needs_review" and len(res.candidates) == 3 and res.card is None   # не угадываем


async def test_name_single_exact_candidate_found(tmp_path):
    enr = Enricher(DB(tmp_path / "t.db"), [adapter(lambda r: httpx.Response(200, json={"suggestions": [PARTY]}))])
    assert (await enr.lookup_name('ООО "Ромашка"')).status == "found"


async def test_no_adapters_is_disabled(tmp_path):
    assert (await Enricher(DB(tmp_path / "t.db"), []).lookup_inn(SBER)).status == "disabled"


def test_inn_file_txt_csv_dedup_and_invalid():
    raw = f"ИНН\n{SBER}\n{GAZPROM};{SBER}\n1234567890\nмусор 12\n".encode("utf-8")
    valid, invalid, trunc = parse_inn_file("list.csv", raw)
    assert valid == [SBER, GAZPROM] and invalid == ["1234567890"] and not trunc


def test_inn_file_xlsx_numeric_cells_and_limit():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ИНН"])
    ws.append([int(SBER)])                 # число, а не строка
    buf = io.BytesIO()
    wb.save(buf)
    assert parse_inn_file("a.xlsx", buf.getvalue())[0] == [SBER]
    with pytest.raises(ValueError):
        parse_inn_file("a.pdf", b"")


def test_inn_limit_50():
    # генерируем 60 валидных ИНН подбором контрольной цифры
    from radar.llm.verify import inn_checksum_ok
    out = []
    n = 770000000
    while len(out) < 60:
        for d in range(10):
            c = f"{n}{d}"
            if inn_checksum_ok(c):
                out.append(c)
        n += 1
    valid, _, trunc = parse_inn_file("a.txt", "\n".join(out).encode())
    assert len(valid) == MAX_INNS and trunc


def test_excel_cards_workbook_has_nd_and_review_sheet():
    cand = OrgCard(inn=SBER, name_full="ООО Ромашка 1")
    data = cards_workbook([(SBER, LookupResult("found", card=parse_party(PARTY))),
                           ("Ромашка", LookupResult("needs_review", candidates=[cand], message="Требует проверки")),
                           ("1234567890", LookupResult("error", message="неверный ИНН"))])
    wb = openpyxl.load_workbook(io.BytesIO(data))
    rows = list(wb["Карточки"].iter_rows(values_only=True))
    assert rows[1][1] == "Найдено" and rows[1][7] == "Иванов Иван Иванович"
    assert rows[2][1] == "Требует проверки" and rows[2][2] == "н/д"
    assert wb["Требует проверки (топ-3)"].max_row == 2


async def test_name_search_is_restricted_to_lnr_by_kladr(tmp_path):
    seen = []

    def handler(req):
        import json as j
        seen.append(j.loads(req.content))
        return httpx.Response(200, json={"suggestions": []})

    res = await Enricher(DB(tmp_path / "t.db"), [adapter(handler)]).lookup_name("Клеверфарм")
    assert seen[0]["locations"] == [{"kladr_id": "9400000000000"}]
    assert res.status == "not_found"      # нет в ЛНР — не подставляем московских однофамильцев
