"""`lnrbank check` — этапы 0–1: TLS, ключевая ставка, загрузка сайтов, привязка к ЛНР, watchlist.

Результат сохраняется в JSON; запись в таблицу `banks` делает конвейер (задача 8).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import yaml

from lnrbank.browser.engine import BrowserEngine
from lnrbank.browser.region import bind_region
from lnrbank.config import CONFIG_DIR, Settings
from lnrbank.net.cbr import fetch_key_rate
from lnrbank.net.tls import check_tls, ssl_context


def load_playbook(path: Path | None = None) -> dict:
    with (path or CONFIG_DIR / "site_playbook.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_check(settings: Settings, today: date | None = None) -> dict:
    today = today or date.today()
    ctx = ssl_context(settings)
    report: dict = {"date": today.isoformat(), "tls": [asdict(r) for r in check_tls(settings)]}
    try:
        rate_date, rate = fetch_key_rate(ctx, today)
        report["key_rate"] = {"date": rate_date, "value": rate}
    except Exception as exc:  # noqa: BLE001 — ставка ЦБ не должна ронять проверку сайтов
        report["key_rate"] = {"error": str(exc)[:200]}

    playbook = load_playbook()
    shots = settings.resolve(settings.storage.raw_dir) / f"check_{today.isoformat()}"
    names = [settings.region.default_city, *settings.region.aliases]
    report["banks"], report["watchlist"] = [], []
    with BrowserEngine(settings, verify=ctx) as engine:
        for bank in settings.banks:
            spec = playbook.get(bank, {}).get("home")
            page = engine.page(bank)
            visit = engine.visit(page, spec["url"] if spec else settings.banks[bank].home)
            row = {"bank": bank, "load": asdict(visit), "region": None, "screenshot": None}
            if visit.ok and spec:
                binding = bind_region(page, spec, city=settings.region.default_city, navigate=False)
                row["region"] = asdict(binding)
            if visit.status is not None:
                row["screenshot"] = engine.screenshot(page, shots / f"{bank}.png")
            report["banks"].append(row)
        for cand in settings.watchlist:
            page = engine.page(cand.code)
            visit = engine.visit(page, cand.offices_url)
            text = page.inner_text("body") if visit.ok else ""
            hits = sorted({n for n in names if n in text})
            report["watchlist"].append(
                {
                    "bank": cand.code,
                    "load": asdict(visit),
                    "in_lnr": "yes" if hits else "unknown",
                    "evidence": hits,
                }
            )

    out = settings.resolve(settings.storage.out_dir) / f"check_{today.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["file"] = str(out)
    return report


def format_report(report: dict) -> str:
    lines = [f"Проверка {report['date']}"]
    kr = report.get("key_rate", {})
    lines.append(
        f"Ключевая ставка ЦБ: {kr.get('value', '—')} % на {kr.get('date', kr.get('error'))}"
    )
    for t in report["tls"]:
        lines.append(f"TLS {'OK  ' if t['ok'] else 'FAIL'} {t['host']}")
    for b in report["banks"]:
        region = b["region"] or {}
        state = (
            f"ЛНР: {region.get('method')} — «{region.get('evidence')}»"
            if region.get("ok")
            else f"ЛНР не подтверждена: {region.get('reason') or b['load']['reason']}"
        )
        lines.append(f"{b['bank']:<6} {'загружен' if b['load']['ok'] else 'не загружен'}; {state}")
    for w in report["watchlist"]:
        lines.append(f"watchlist {w['bank']}: {w['in_lnr']} {w['evidence']}")
    lines.append(f"Отчёт: {report.get('file')}")
    return "\n".join(lines)
