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


def candidate_text(c: dict, short: bool = True, esc: bool = True) -> str:
    """«Название (ИНН …, регион)» для вариантов «требует проверки». short — укороченный вид для Telegram."""
    name = c.get("name_short") or c.get("name_full") or "н/д"
    if short and len(name) > 38:
        name = name[:37] + "…"
    addr = (c.get("address") or "")
    region = "ЛНР" if "Луганская Народная" in addr else (addr.split(",")[0][:20] if addr else "")
    text = f"{name} (ИНН {c.get('inn') or 'н/д'}{', ' + region if region else ''})"
    return escape(text) if esc else text


def _fmt_event(ev: dict) -> str:
    """Один блок события. Всё, чего нет в источнике, пишем «н/д»."""
    lines = [f"<b>{escape(ev['title'])}</b>", escape(ev["summary"])]
    orgs = ev.get("organizations") or []
    enr = ev.get("enriched") or {}
    matched = enr.get("matched_org")                  # какая организация новости получила карточку
    card = enr.get("card") if enr.get("status") == "found" else None
    if orgs:
        parts = []
        for o in orgs[:2]:
            is_matched = bool(enr) and (matched == o["name"] or (matched is None and o is orgs[0]))
            if is_matched and card:                   # данные из DaData (подтверждены источником)
                parts.append(f"{escape(card.get('name_short') or card.get('name_full') or o['name'])} (ИНН {card.get('inn') or 'н/д'})")
            elif is_matched and enr.get("status") == "needs_review":
                parts.append(f"{escape(o['name'])} (ИНН: требует проверки)")
            else:
                parts.append(f"{escape(o['name'])} (ИНН {o.get('inn_if_in_text') or 'н/д'})")
        lines.append("🏷 " + "; ".join(parts))
    if enr.get("status") == "needs_review" and enr.get("candidates"):
        lines.append("🔎 Варианты: " + " · ".join(candidate_text(c) for c in enr["candidates"][:3]))
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
                 tz: str = "Europe/Moscow", max_events: int = 12, min_score: int = 3,
                 dash_min_score: int = 2) -> str:
    z = ZoneInfo(tz)
    period = f"{since.astimezone(z):%d.%m %H:%M} – {until.astimezone(z):%d.%m %H:%M}"
    head = f"📡 <b>Радар ЛНР</b> · {period}"
    foot = f"\n⚠️ не удалось прочитать: {failed_channels} {_plural(failed_channels, 'канал', 'канала', 'каналов')}" if failed_channels else ""

    shown = sorted((e for e in events if e["relevance_score"] >= min_score),
                   key=lambda e: -e["relevance_score"])
    dash_n = sum(1 for e in events if e["relevance_score"] >= dash_min_score)
    if not shown:
        extra = f"\nВ дашборде ещё {dash_n} событ. с оценкой от {dash_min_score}⭐." if dash_n else ""
        return f"{head}\nНовых значимых событий нет (от {min_score}⭐).{extra}{foot}"

    counts = defaultdict(int)
    for e in shown:
        counts[e["category"]] += 1
    summary = " ".join(f"{CATEGORIES[c][0]}{n}" for c, n in sorted(counts.items()))
    head += f"\nСобытий от {min_score}⭐: {len(shown)} · {summary}"

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
    hidden = dash_n - included          # всё, что не влезло в сообщение, но есть в дашборде (от 2⭐)
    if hidden > 0:
        out.append(f"\n…и ещё {hidden} — в приложенном дашборде.")
    return "\n".join(out) + foot
