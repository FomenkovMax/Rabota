"""Сборка одного дайджест-сообщения Telegram (HTML, ≤ 4096 символов)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from ..llm.schemas import CATEGORIES

TG_LIMIT = 4096


def _plural(n: int, one: str, few: str, many: str) -> str:
    """1 канал, 2 канала, 5 каналов."""
    n10, n100 = n % 10, n % 100
    return one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many


def _fmt_event(ev: dict) -> str:
    """Один блок события. Всё, чего нет в источнике, пишем «н/д»."""
    lines = [f"<b>{escape(ev['title'])}</b>", escape(ev["summary"])]
    orgs = ev.get("organizations") or []
    enr = ev.get("enriched") or {}
    card = enr.get("card") if enr.get("status") == "found" else None
    if orgs:
        parts = []
        for k, o in enumerate(orgs[:2]):
            if k == 0 and card:                       # данные из DaData (подтверждены источником)
                parts.append(f"{escape(card.get('name_short') or card.get('name_full') or o['name'])} (ИНН {card.get('inn') or 'н/д'})")
            elif k == 0 and enr.get("status") == "needs_review":
                parts.append(f"{escape(o['name'])} (ИНН: требует проверки)")
            else:
                parts.append(f"{escape(o['name'])} (ИНН {o.get('inn_if_in_text') or 'н/д'})")
        lines.append("🏷 " + "; ".join(parts))
    persons = ev.get("persons") or []
    lpr = None
    if card and card.get("director"):
        lpr = card["director"] + (f", {card['director_post']}" if card.get("director_post") else "") + " (ЛПР)"
    elif persons:
        lpr = persons[0]["name"] + (f", {persons[0]['position']}" if persons[0].get("position") else "")
    if lpr:
        lines.append("👤 " + escape(lpr))
    lines.append("💵 " + escape(ev.get("fin_effect_text") or "н/д"))
    if ev.get("business_opportunity"):
        lines.append("🎯 " + escape(ev["business_opportunity"]))
    links = ev.get("source_urls") or []
    if links:
        lines.append(" · ".join(f'<a href="{escape(u)}">источник {i}</a>' for i, u in enumerate(links[:3], 1)))
    return "\n".join(lines)


def build_digest(events: list[dict], since: datetime, until: datetime, failed_channels: int,
                 tz: str = "Europe/Moscow", max_events: int = 12, min_score: int = 2) -> str:
    z = ZoneInfo(tz)
    period = f"{since.astimezone(z):%d.%m %H:%M} – {until.astimezone(z):%d.%m %H:%M}"
    head = f"📡 <b>Радар ЛНР</b> · {period}"
    foot = f"\n⚠️ не удалось прочитать: {failed_channels} {_plural(failed_channels, 'канал', 'канала', 'каналов')}" if failed_channels else ""

    shown = sorted((e for e in events if e["relevance_score"] >= min_score),
                   key=lambda e: -e["relevance_score"])
    if not shown:
        return f"{head}\nНовых значимых событий нет.{foot}"

    counts = defaultdict(int)
    for e in events:
        counts[e["category"]] += 1
    summary = " ".join(f"{CATEGORIES[c][0]}{n}" for c, n in sorted(counts.items()))
    head += f"\nСобытий: {len(events)} · {summary}"

    top = shown[:max_events]
    by_cat = defaultdict(list)
    for e in top:
        by_cat[e["category"]].append(e)

    out = [head]
    used = len(head) + len(foot) + 80  # запас под строку «ещё N»
    included = 0
    for cat in sorted(by_cat):
        block_head = f"\n{CATEGORIES[cat][0]} <b>{CATEGORIES[cat][1]}</b>"
        chunk = [block_head]
        for e in by_cat[cat]:
            text = f"\n⭐{e['relevance_score']} " + _fmt_event(e)
            if used + len(block_head) + sum(map(len, chunk)) + len(text) > TG_LIMIT:
                break
            chunk.append(text)
            included += 1
        if len(chunk) > 1:
            out.extend(chunk)
            used += sum(map(len, chunk))
    hidden = len(events) - included
    if hidden > 0:
        out.append(f"\n…и ещё {hidden} — в приложенном дашборде.")
    return "\n".join(out) + foot
