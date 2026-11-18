"""Read instrument fields returned to the public T-Bank catalogue pages."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .browser import PageFailed, PageReader, PageTooSlow
from .crawl_adapter import is_blocked, is_not_found
from .others import TbankAdapter
from ..pipeline import Config
from ..securities import issue_kind, valid_isin

_SYMBOL_FIELDS = ("ticker", "showName", "isin", "currency", "lotSize", "exchange",
                  "tradeQualInvestor", "noTrade", "isOTC")
_ISSUE_FIELDS = ("instrumentStatus", "faceValue", "couponValue", "couponPeriodDays",
                 "matDate", "floatingCoupon", "perpetual", "subordinated")


def catalogue_rows(data: dict, *, adapter: TbankAdapter, kind: str) -> tuple[set[str], dict]:
    root = f"{adapter.base_url}/invest/{kind}/"
    links = {
        unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1]).casefold(): href
        for href in adapter._links(data.get("links") or [])
        if href.startswith(root) and issue_kind(href)
    }
    matched = {}
    for response in data.get("network", []):
        url = urlsplit(response["url"])
        if (url.scheme != "https" or url.netloc != "www.tbank.ru"
                or url.path != f"/api/trading/{kind}/list" or response.get("status") != 200):
            continue
        payload = json.loads(response["body"])
        if payload.get("status") != "Ok":
            continue
        for issue in payload.get("payload", {}).get("values", []):
            symbol = issue.get("symbol") or {}
            ticker = symbol.get("ticker") or ""
            href = links.get(ticker.casefold())
            if not href or not symbol.get("showName"):
                continue
            identity = {key: symbol[key] for key in _SYMBOL_FIELDS if key in symbol}
            if identity.get("isin") and not valid_isin(identity["isin"]):
                identity.pop("isin")
            fields = {key: issue[key] for key in _ISSUE_FIELDS if key in issue}
            matched[href] = {"symbol": identity, "fields": fields}
    return set(links.values()), matched


def read_rows(reader: PageReader, adapter: TbankAdapter, kind: str,
              inventory: dict, destination: Path) -> dict:
    root = f"{adapter.base_url}/invest/{kind}/"
    if inventory["source"] != root or not inventory["pages"]:
        raise ValueError(f"Нет страниц проверенной витрины {root}")
    pages, errors = {}, {}
    temporary = destination.with_suffix(".tmp")
    for number, page in enumerate(inventory["pages"], 1):
        if not page.startswith(root) or urlsplit(page).path != urlsplit(root).path:
            raise ValueError(f"Посторонний адрес витрины {page}")
        try:
            data = reader.read(page)
            if is_blocked(data) or is_not_found(data):
                raise ValueError("страница недоступна")
            visible, matched = catalogue_rows(data, adapter=adapter, kind=kind)
            if not matched:
                raise ValueError("нет строк, совпадающих с видимыми ссылками")
            pages[page] = {"rows": matched, "unmatched": sorted(visible - matched.keys())}
            print(kind, number, len(matched), len(visible - matched.keys()), flush=True)
        except (PageFailed, PageTooSlow, ValueError) as exc:
            errors[page] = str(exc)
            print(kind, number, str(exc), flush=True)
        state = {
            "source": root, "updated_at": datetime.now(timezone.utc).isoformat(),
            "pages": pages, "errors": errors, "expected_pages": len(inventory["pages"]),
        }
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="directory with stocks.json and bonds.json")
    parser.add_argument("output", type=Path, help="output directory for catalogue rows")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adapter = TbankAdapter(region=None, settings=Config.load().bank_settings("tbank"))
    settings = adapter.browser_settings()
    settings.expand = False
    settings.record_network = True
    with PageReader(settings) as reader:
        for kind in ("stocks", "bonds"):
            name = kind + ".json"
            inventory = json.loads((args.inventory / name).read_text(encoding="utf-8"))
            read_rows(reader, adapter, kind, inventory, args.output / name)


if __name__ == "__main__":
    main()
