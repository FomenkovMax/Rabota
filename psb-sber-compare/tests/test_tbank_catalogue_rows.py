import json

from src.banks.others import TbankAdapter
from src.banks.tbank_catalogue_rows import catalogue_rows


def test_catalogue_rows_use_public_visible_issue_links_and_validate_isin():
    root = "https://www.tbank.ru/invest/stocks/"
    response = {
        "url": "https://www.tbank.ru/api/trading/stocks/list?sessionId=example",
        "status": 200,
        "body": json.dumps({"status": "Ok", "payload": {"values": [
            {"symbol": {"ticker": "SBER", "showName": "Сбер", "isin": "RU0009029540"},
             "faceValue": 1, "price": {"value": 100}},
            {"symbol": {"ticker": "GAZP", "showName": "Газпром", "isin": "RU0007661626"}},
            {"symbol": {"ticker": "NOT_VISIBLE", "showName": "Лишняя строка"}},
        ]}}),
    }
    adapter = TbankAdapter(region=None)
    visible, rows = catalogue_rows({
        "links": [(root + name + "/", name) for name in ("SBER", "GAZP", "VTBR")],
        "network": [response],
    }, adapter=adapter, kind="stocks")

    assert visible == {root + name for name in ("SBER", "GAZP", "VTBR")}
    assert set(rows) == {root + "SBER", root + "GAZP"}
    assert rows[root + "SBER"]["symbol"]["isin"] == "RU0009029540"
    assert rows[root + "SBER"]["fields"] == {"faceValue": 1}
    assert "isin" not in rows[root + "GAZP"]["symbol"]
    assert "sessionId" not in str(rows)


def test_snapshot_includes_the_public_catalogue_rows(tmp_path, monkeypatch):
    from zipfile import ZipFile
    from bot import service

    monkeypatch.setattr(service, "ROOT", tmp_path)
    rows = tmp_path / "data" / "tbank-inventory" / "catalogue-rows"
    rows.mkdir(parents=True)
    (rows / "stocks.json").write_text("{}", encoding="utf-8")
    (rows / "bonds.tmp").write_text("{}", encoding="utf-8")

    with ZipFile(service.full_snapshot_archive()) as archive:
        assert archive.namelist() == ["tbank-inventory/catalogue-rows/stocks.json"]


def test_catalogue_read_resumes_after_last_saved_page(tmp_path):
    from src.banks.tbank_catalogue_rows import read_rows

    root = "https://www.tbank.ru/invest/stocks/"
    page_two = root + "?start=12&end=24"
    output = tmp_path / "stocks.json"
    output.write_text(json.dumps({
        "source": root, "expected_pages": 2, "pages": {root: {"rows": {"SBER": {}}}},
    }), encoding="utf-8")
    seen = []

    class Reader:
        def read(self, url):
            seen.append(url)
            return {"links": [], "text": "Акции"}

    result = read_rows(Reader(), TbankAdapter(region=None), "stocks",
                       {"source": root, "pages": {root: [], page_two: []}}, output)
    assert seen == [page_two]
    assert root in result["pages"]
    assert page_two in result["errors"]
