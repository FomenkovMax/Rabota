"""Collect public T-Bank listing fields using the catalogue's own request."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .browser import browser_session
from .others import TbankAdapter
from .tbank_catalogue_rows import catalogue_rows
from ..pipeline import Config

_HEADERS = {"accept", "content-type", "origin", "referer", "user-agent"}
_PAUSE_SECONDS = 1.5


def _tickers(payload: dict) -> set[str]:
    return {row["symbol"]["ticker"] for row in payload["payload"]["values"]}


def _request_template(page, kind: str, root: str):
    path = f"/api/trading/{kind}/list"

    def is_catalogue(response) -> bool:
        url = urlsplit(response.url)
        return (url.scheme == "https" and url.netloc == "www.tbank.ru"
                and url.path == path and response.status == 200
                and response.request.method == "POST")

    with page.expect_response(is_catalogue, timeout=45_000) as captured:
        page.goto(root, wait_until="domcontentloaded", timeout=45_000)
    original = captured.value
    params = original.request.post_data_json
    headers = {key: value for key, value in original.request.headers.items() if key in _HEADERS}
    check = page.request.post(original.url, data=params, headers=headers,
                              timeout=15_000, max_redirects=0)
    if not check.ok or _tickers(original.json()) != _tickers(check.json()):
        raise ValueError(f"Ответ публичного запроса {kind} не совпал с открытой витриной")
    return original.url, headers, params


def _page_body(template: dict, root: str, url: str) -> dict:
    parts = urlsplit(url)
    if urlsplit(root)._replace(query="", fragment="").geturl() != parts._replace(query="", fragment="").geturl():
        raise ValueError("Посторонний адрес витрины")
    query = parse_qs(parts.query)
    return {**template, **{key: int(query[key][0]) for key in ("start", "end") if key in query}}


def collect_public_rows(page, adapter: TbankAdapter, kind: str, inventory: dict,
                        output: Path) -> None:
    from playwright.sync_api import Error as BrowserError

    root = f"{adapter.base_url}/invest/{kind}/"
    if inventory["source"] != root or not inventory["pages"]:
        raise ValueError(f"Нет страниц проверенной витрины {root}")
    links = [[url, ""] for group in inventory["pages"].values() for url in group]
    route, headers, template = _request_template(page, kind, root)
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    if previous and (previous["source"] != root or previous["expected_pages"] != len(inventory["pages"])):
        raise ValueError("Промежуточный файл относится к другой витрине")
    pages = {url: data for url, data in previous.get("pages", {}).items() if url in inventory["pages"]}
    errors = {}
    temporary = output.with_suffix(".tmp")
    for index, url in enumerate(inventory["pages"], 1):
        if url in pages:
            continue
        body = _page_body(template, root, url)
        time.sleep(_PAUSE_SECONDS)
        try:
            response = page.request.post(route, data=body, headers=headers,
                                         timeout=18_000, max_redirects=0)
            if response.status in (401, 403, 429):
                raise RuntimeError(f"Витрина {kind} остановлена, HTTP {response.status}")
            if not response.ok:
                raise ValueError(f"HTTP {response.status}")
            returned = _tickers(response.json())
            _, rows = catalogue_rows({
                "links": links,
                "network": [{"url": route, "status": response.status, "body": response.text()}],
            }, adapter=adapter, kind=kind)
            if not returned or not rows:
                raise ValueError("ответ не сопоставлен со ссылками проверенной витрины")
            known = {row["symbol"]["ticker"] for row in rows.values()}
            pages[url] = {"rows": rows, "new_tickers": sorted(returned - known),
                          "read_at": datetime.now(timezone.utc).isoformat()}
            print(kind, index, len(rows), "новые тикеры", len(returned - known), flush=True)
        except (BrowserError, ValueError, KeyError, TypeError) as error:
            # Browser diagnostics can contain the anonymous session URL.
            errors[url] = type(error).__name__ if isinstance(error, BrowserError) else str(error)
            print(kind, index, errors[url], flush=True)
        state = {"source": root, "expected_pages": len(inventory["pages"]),
                 "updated_at": datetime.now(timezone.utc).isoformat(),
                 "pages": pages, "errors": errors, "method": "verified_public_catalogue_request"}
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output)


def main() -> None:
    from playwright.sync_api import Error as BrowserError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adapter = TbankAdapter(region=None, settings=Config.load().bank_settings("tbank"))
    settings = adapter.browser_settings()
    settings.expand = False
    try:
        with browser_session(settings) as browser:
            page = browser._context.new_page()
            for kind in ("stocks", "bonds"):
                name = kind + ".json"
                inventory = json.loads((args.inventory / name).read_text(encoding="utf-8"))
                collect_public_rows(page, adapter, kind, inventory, args.output / name)
    except BrowserError as error:
        raise SystemExit(f"Ошибка браузера при чтении витрины: {type(error).__name__}") from None


if __name__ == "__main__":
    main()
