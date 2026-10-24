"""Эталон для адаптера ЦМР: прогоняет НАСТОЯЩИЙ калькулятор на сайте банка по сетке параметров и сохраняет результаты.

Зачем Playwright: адаптер портирует логику калькулятора на Python, а сверять порт нужно с самим сайтом. Для обычного сбора
данных браузер НЕ нужен (данные лежат в HTML как JSON) — этот скрипт только для разработки/проверки.

Честность: User-Agent представляется как бот; перед загрузкой проверяется robots.txt обычным загрузчиком проекта; страниц две,
между ними пауза; защита сайта не обходится (сайт ЦМР нас не блокирует).

Запуск (нужен пакет playwright и установленный Chromium):
    python tools/cmr_calculator_golden.py --out tests/fixtures/cmr_calculator_golden.json
"""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from bankintel.sources.base import SourceRef
from bankintel.sources.fetcher import HttpFetcher

UA = "BankIntelBot/0.1 (research prototype; respects robots.txt)"
PAGES = {
    "deposits": "https://www.cmrbank.ru/person/person-deposit/deposit-calc/",
    "accounts": "https://www.cmrbank.ru/person/person-deposit/deposit-account/",
}
SUMS = [1, 10_000, 49_999, 50_000, 100_000, 300_000, 500_000, 1_000_000, 5_000_000]
TERMS = [31, 45, 60, 91, 100, 150, 181, 276, 300, 367, 400, 550, 730, 1095]
PAYOUTS = ["at_end", "at_month_deposit", "at_month_account"]
FLAGS = [(False, False), (True, False), (False, True)]  # (пополнение, снятие)

JS = """
async ({sums, terms, payouts, flags}) => {
  const st = document.querySelector('#app').__vue_app__._instance.setupState.state;
  const tick = () => new Promise(r => setTimeout(r, 0));
  const out = {};
  // у страницы накопительных счетов калькулятора нет (только список) — для неё эталон только «каталожный»
  if (st.input) for (const sum of sums) for (const term of terms) for (const pay of payouts) for (const [rep, wd] of flags) {
    st.input.sum = sum; st.input.term = term; st.input.pct_pay = pay; st.input.replenish = rep; st.input.withdraw = wd;
    await tick();
    for (const d of Object.values(st.deposites)) {
      const c = d.calculation;
      const key = [sum, term, pay, rep ? 1 : 0, wd ? 1 : 0].join('|');
      (out[d.id] = out[d.id] || {})[key] = c.disabled ? null : [c.rate, c.term, c.replenish ? 1 : 0, c.withdraw ? 1 : 0, c.profit_sum];
    }
  }
  const meta = Object.values(st.deposites).map(d => ({id: d.id, name: d.name, type: d.type, max_rate: d.max_rate, min_sum: d.min_sum,
      min_term: d.min_term, max_term: d.max_term, fixed: d.is_fixed_term, has_replenish: !!d.has_replenish, has_withdraw: !!d.has_withdraw,
      pct_pay_at_month: !!d.pct_pay_at_month, pct_pay_at_end: !!d.pct_pay_at_end}));
  return {meta, results: out};
}
"""


async def robots_ok(urls) -> None:
    f = HttpFetcher(UA, min_interval_s=2)
    try:
        for u in urls:
            doc, diag = await f.fetch(SourceRef("golden", u, "discovery"))
            if doc is None:
                raise SystemExit(f"{u}: {diag.outcome.value} {diag.error or ''} — не загружаем")
    finally:
        await f.aclose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    asyncio.run(robots_ok(PAGES.values()))

    from playwright.sync_api import sync_playwright

    exe = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    golden = {"captured_at": datetime.now(UTC).isoformat(), "user_agent": UA, "grid": {"sums": SUMS, "terms": TERMS, "payouts": PAYOUTS}, "pages": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        ctx = browser.new_context(user_agent=UA, locale="ru-RU")
        for name, url in PAGES.items():
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=45_000)
            golden["pages"][name] = {"url": url, **page.evaluate(JS, {"sums": SUMS, "terms": TERMS, "payouts": PAYOUTS, "flags": FLAGS})}
            page.close()
            time.sleep(2)
        browser.close()
    Path(args.out).write_text(json.dumps(golden, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(v) for pg in golden["pages"].values() for v in pg["results"].values())
    print(f"сохранено {n} точек эталона в {args.out}")


if __name__ == "__main__":
    main()
