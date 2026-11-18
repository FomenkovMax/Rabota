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


def test_snapshot_excludes_securities_and_keeps_office_evidence(tmp_path, monkeypatch):
    from zipfile import ZipFile
    from bot import service

    monkeypatch.setattr(service, "ROOT", tmp_path)
    rows = tmp_path / "data" / "tbank-inventory" / "catalogue-rows"
    rows.mkdir(parents=True)
    (rows / "stocks.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "vtb-lugansk-broker-office.json").write_text("{}", encoding="utf-8")
    pages = tmp_path / "data" / "pages-all"
    pages.mkdir()
    (pages / "issue.txt").write_text("URL: https://www.tbank.ru/invest/stocks/GAZP", encoding="utf-8")

    with ZipFile(service.full_snapshot_archive()) as archive:
        assert archive.namelist() == ["data/vtb-lugansk-broker-office.json"]


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


def test_public_catalogue_request_changes_only_pagination():
    from src.banks.tbank_public_catalogue import _page_body

    root = "https://www.tbank.ru/invest/stocks/"
    template = {"start": 0, "end": 12, "sortType": "ByPopularity", "isPrivate": False}
    result = _page_body(template, root, root + "?start=12&end=24&sortType=other")
    assert result == {**template, "start": 12, "end": 24}
    assert template["start"] == 0


def test_listing_rows_retain_source_and_prefer_detail_pages(tmp_path):
    from src import securities
    from src.psb.parser import Product

    root = "https://www.tbank.ru/invest/stocks/"
    existing = Product(bank="Т-Банк", title="Карточка Сбера", source_url=root + "SBER/",
                       terms={securities.KIND: "Акция", securities.ISIN: "RU0009029540"})
    (tmp_path / "stocks.json").write_text(json.dumps({
        "source": root, "pages": {root: {"rows": {
            root + "SBER": {"symbol": {"showName": "Дубль из витрины"}},
            root + "GAZP": {"symbol": {"showName": "Газпром", "isin": "RU0007661625", "ticker": "GAZP"}},
        }}},
    }), encoding="utf-8")
    listing = securities.catalogue_products(tmp_path, [existing])
    assert [item.title for item in listing] == ["Газпром"]
    assert listing[0].terms[securities.CATALOGUE_SOURCE] == root
    assert listing[0].terms[securities.ISIN] == "RU0007661625"


def test_allstate_ticker_is_an_issue_not_a_section():
    from src import securities

    root = "https://www.tbank.ru/invest/stocks/"
    assert securities.issue_kind(root + "ALL") == "Акция"
    assert not securities.issue_kind(root + "all")


def test_public_detailed_response_is_reported_as_a_card_without_city_confirmation(tmp_path):
    from src import availability, securities
    from src.banks.tbank_detail_fields import instrument_fields

    url = "https://www.tbank.ru/invest/bonds/SU26233RMFS5"
    result = instrument_fields({"status": "Ok", "payload": {
        "symbol": {"ticker": "SU26233RMFS5", "showName": "ОФЗ 26233", "isin": "RU000A101F94"},
        "couponValue": 30, "price": 985,
    }}, "SU26233RMFS5")
    assert result["fields"] == {"couponValue": 30}
    output = tmp_path / "details.jsonl"
    output.write_text(json.dumps({
        **result, "url": url, "read_at": "2026-11-18T11:21:00+00:00",
    }) + "\n", encoding="utf-8")
    products = securities.detailed_public_products(output)
    assert len(products) == 1
    assert products[0].terms[securities.ISIN] == "RU000A101F94"
    assert not availability.status_of(products[0], region_method="selector").city_confirmed
    assert products[0].terms[securities.DETAIL_SOURCE] == url
