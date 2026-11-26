"""Read detailed public responses for the exact T-Bank audit gaps."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from src.banks.browser import browser_session
from src.banks.others import TbankAdapter
from src.pipeline import Config
from src.securities import valid_isin

FIELDS = ("faceValue", "faceValueOriginal", "faceValueOriginalCurrency", "couponValue",
          "couponPeriodDays", "matDate", "endDate", "floatingCoupon", "perpetual",
          "subordinated", "couponType", "instrumentStatus", "instrumentStatusShortDesc",
          "exchangeStatus", "taxFree", "liquidity", "stockType")
SYMBOL = ("ticker", "showName", "isin", "currency", "lotSize", "exchange",
          "exchangeShowName", "sector", "countryOfRiskBriefName", "noTrade",
          "tradeQualInvestor", "isOTC", "classCode", "symbolType")

def instrument_fields(payload: dict, ticker: str) -> dict:
    value = payload.get("payload") or {}
    symbol = value.get("symbol") or {}
    if payload.get("status") != "Ok" or str(symbol.get("ticker","")).casefold()!=ticker.casefold() or not symbol.get("showName"):
        raise ValueError("ответ не подтвердил тикер")
    identity = {k:symbol[k] for k in SYMBOL if k in symbol}
    if identity.get("isin") and not valid_isin(str(identity["isin"])):
        identity.pop("isin")
    return {"symbol":identity,"fields":{k:value[k] for k in FIELDS if k in value}}

def capture(page, kind, sample):
    route_path=f"/api/trading/{kind}/get"
    with page.expect_response(lambda r: urlsplit(r.url).scheme=="https"
                              and urlsplit(r.url).hostname=="www.tbank.ru"
                              and urlsplit(r.url).path==route_path
                              and r.request.method=="POST" and r.status==200,timeout=45000) as event:
        page.goto(sample,wait_until="domcontentloaded",timeout=45000)
    origin=event.value
    template=origin.request.post_data_json
    assert set(template)=={"ticker"}
    headers={k:v for k,v in origin.request.headers.items()
             if k in {"accept","content-type","origin","referer","user-agent"}}
    result=page.request.post(origin.url,data=template,headers=headers,timeout=18000,max_redirects=0)
    assert result.ok and instrument_fields(origin.json(),template["ticker"])==instrument_fields(result.json(),template["ticker"])
    return origin.url,headers

def main() -> int:
    from playwright.sync_api import Error as BrowserError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--kind", choices=("stocks", "bonds"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adapter=TbankAdapter(region=None,settings=Config.load().bank_settings("tbank"))
    settings=adapter.browser_settings()
    inventory=json.loads(args.audit.read_text(encoding="utf-8"))["catalogues"]
    samples={"stocks":"https://www.tbank.ru/invest/stocks/SBER/","bonds":"https://www.tbank.ru/invest/bonds/SU26233RMFS5/"}
    target=args.output / "details.jsonl"
    done={json.loads(line)["url"] for line in target.read_text(encoding="utf-8").splitlines()} if target.exists() else set()
    with browser_session(settings) as browser, target.open("a",encoding="utf-8") as output, (args.output / "failures.jsonl").open("a",encoding="utf-8") as failures:
        page=browser._context.new_page()
        for kind in ((args.kind,) if args.kind else ("stocks", "bonds")):
            route,headers=capture(page,kind,samples[kind])
            urls=inventory[kind]["missing_issue_urls"]
            print(kind,"точный список",len(urls),flush=True)
            for index,url in enumerate(urls,1):
                if url in done:
                    continue
                split=urlsplit(url)
                assert split.scheme=="https" and split.hostname=="www.tbank.ru" and split.path.startswith(f"/invest/{kind}/")
                ticker=unquote(split.path.rstrip("/").rsplit("/",1)[-1])
                time.sleep(1.5)
                try:
                    response=page.request.post(route,data={"ticker":ticker},headers=headers,timeout=18000,max_redirects=0)
                    if response.status in (401,403,429):
                        print(kind,"остановлен HTTP",response.status,flush=True)
                        return 2
                    if not response.ok:
                        raise ValueError(f"HTTP {response.status}")
                    result=instrument_fields(response.json(),ticker)
                    result.update(url=url,kind=kind,read_at=datetime.now(timezone.utc).isoformat())
                    output.write(json.dumps(result,ensure_ascii=False)+"\n")
                    output.flush()
                except (BrowserError,ValueError,KeyError,TypeError) as error:
                    reason=type(error).__name__ if isinstance(error,BrowserError) else str(error)
                    failures.write(json.dumps({"url":url,"error":reason},ensure_ascii=False)+"\n")
                    failures.flush()
                if index%30==0 or index<=3:
                    print(kind,index,"из",len(urls),flush=True)
    return 0

if __name__ == "__main__":
    from playwright.sync_api import Error as BrowserError

    try:
        raise SystemExit(main())
    except BrowserError as exc:
        raise SystemExit(type(exc).__name__) from None
