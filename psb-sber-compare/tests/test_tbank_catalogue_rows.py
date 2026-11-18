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
