"""Одностраничный PDF «Радар ЛНР — главное»: главные новости с визуалом (A4, одна страница).

Визуал — НАСТОЯЩИЕ фото из исходных постов (превью t.me), без ИИ-генерации: сгенерированная картинка
«события» была бы выдумкой. Нет фото — цветная плашка категории. Сбой картинки/PDF дайджест не ломает.
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ..llm.schemas import CATEGORIES

log = logging.getLogger(__name__)

# Цвет и короткая подпись категории (белый текст на цвете — контраст ≥ 4.5:1)
CAT_STYLE = {
    1: ("#1B7F3B", "НОВЫЙ ИГРОК"), 2: ("#2B6CB0", "ИЗМЕНЕНИЯ"), 3: ("#C53030", "РИСК"),
    4: ("#975A16", "ИНВЕСТИЦИИ"), 5: ("#553C9A", "РГС"), 6: ("#4A5568", "СИЛОВИКИ"),
    7: ("#0B7285", "ЦИФРА И ИИ"), 8: ("#B3501B", "КОНКУРЕНТЫ"),
}
IMG_HOSTS = ("telesco.pe", "telegram.org")      # фото берём только с CDN Telegram
MAX_IMG_BYTES = 4_000_000
MAX_NEWS = 7                                     # 1 крупная + 6 карточек


def _cut(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip(" ,.;:—-") + "…"


def _stars(n: int) -> str:
    return "★" * n + "☆" * (5 - n)


def _short_name(card_or_org: dict | None, fallback: str) -> str:
    return (card_or_org or {}).get("name_short") or fallback


def _org_line(ev: dict) -> str:
    """«Организация (ИНН …)» — ИНН только из реестра/текста, иначе «н/д» или «требует проверки»."""
    from .excel import matched_org
    org = matched_org(ev)
    enr = ev.get("enriched") or {}
    card = enr.get("card") if enr.get("status") == "found" else None
    name = _short_name(card, org.get("name") or "")
    if not name:
        return ""
    if card:
        inn = card.get("inn") or "н/д"
    elif enr.get("status") == "needs_review":
        inn = "требует проверки"
    else:
        inn = org.get("inn_if_in_text") or "н/д"
    return f"{_cut(name, 44)} · ИНН {inn}"


def _lpr(ev: dict) -> str:
    card = (ev.get("enriched") or {}).get("card") if (ev.get("enriched") or {}).get("status") == "found" else None
    if card and card.get("director"):
        return f"ЛПР: {card['director']}"
    persons = ev.get("persons") or []
    if persons:
        return f"{persons[0]['name']}" + (f", {persons[0]['position']}" if persons[0].get("position") else "")
    return ""


# ---------------------------------------------------------------- картинки
async def fetch_images(events: list[dict], client: httpx.AsyncClient | None = None) -> dict[int, str]:
    """Скачивает фото событий -> {индекс события: data-URI jpeg}. Любая ошибка = нет фото у этого события."""
    from PIL import Image

    own = client or httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=False)
    out: dict[int, str] = {}
    try:
        for i, ev in enumerate(events):
            url = ev.get("image_url")
            if not url:
                continue
            u = urlparse(url)
            if u.scheme != "https" or not any((u.hostname or "").endswith(h) for h in IMG_HOSTS):
                continue
            try:
                r = await own.get(url)
                if r.status_code != 200 or len(r.content) > MAX_IMG_BYTES:
                    continue
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.thumbnail((900, 900))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                out[i] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception as e:  # картинка не критична
                log.info("фото для PDF не загружено (%s): %s", type(e).__name__, url[:60])
    finally:
        if client is None:
            await own.aclose()
    return out


# ---------------------------------------------------------------- вёрстка
CSS = """
@page { size: A4; margin: 8mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Liberation Sans", "DejaVu Sans", sans-serif; font-size: 8.6pt; color: #17201b; line-height: 1.28; }
.head { background: #21A038; color: #fff; padding: 5mm 6mm; border-radius: 3mm; }
.head h1 { margin: 0; font-size: 19pt; letter-spacing: .5pt; }
.head .sub { font-size: 8.5pt; opacity: .95; margin-top: 1mm; }
.chips { margin-top: 2.2mm; }
.chip { display: inline-block; background: rgba(255,255,255,.18); border-radius: 99px; padding: .6mm 2.4mm; margin: 0 1.2mm .8mm 0; font-size: 7.8pt; font-weight: bold; }
.hero { margin-top: 4mm; border: .3mm solid #dfe6e2; border-radius: 3mm; overflow: hidden; }
.hero table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.hero td { vertical-align: top; padding: 0; }
.hero .pic { width: 78mm; height: 64mm; }
.hero .body { padding: 3mm 5mm; }
.hero h2 { margin: 1.4mm 0 1.6mm; font-size: 14.5pt; line-height: 1.18; }
.hero .sum { font-size: 9.4pt; }
.card td, .hero td { vertical-align: top; }
.pic img { width: 100%; object-fit: cover; display: block; }
.card .pic img, .card .pic .ph { height: 49mm; }
.hero .pic img, .hero .pic .ph { height: 64mm; }
.clip { overflow: hidden; }
.ph { width: 100%; color: #fff; text-align: center; font-weight: bold; }
.ph span { display: block; padding-top: 22mm; font-size: 15pt; letter-spacing: 1pt; }
.cards { margin-top: 1mm; width: 100%; border-collapse: collapse; table-layout: fixed; }
.cards > tbody > tr > td { vertical-align: top; width: 50%; padding: 2mm 0 1mm 0; }
.cards > tbody > tr > td:first-child { padding-right: 1.5mm; }
.cards > tbody > tr > td:last-child { padding-left: 1.5mm; }
.card { border: .3mm solid #dfe6e2; border-radius: 2.6mm; overflow: hidden; height: 49mm; }
.card table { width: 100%; height: 49mm; border-collapse: collapse; table-layout: fixed; }
.card td.pic { width: 33mm; height: 49mm; }
.card td.txt { padding: 2.6mm 3mm; }
.tag { display: inline-block; color: #fff; font-size: 6.8pt; font-weight: bold; padding: .5mm 2mm; border-radius: 1.2mm; letter-spacing: .3pt; }
.stars { color: #d69e2e; font-size: 8.4pt; letter-spacing: .6pt; margin-left: 1.5mm; }
.card h3 { margin: 1.4mm 0 1mm; font-size: 9.6pt; line-height: 1.2; }
.card .sum { font-size: 7.9pt; color: #2d3a33; }
.meta { font-size: 7.1pt; color: #5d6b63; margin-top: 1mm; }
.meta b { color: #17201b; }
.foot { margin-top: 3mm; font-size: 6.9pt; color: #5d6b63; border-top: .25mm solid #dfe6e2; padding-top: 1.8mm; }
a { color: inherit; text-decoration: none; }
"""


def _pic(ev: dict, idx: int, images: dict[int, str]) -> str:
    color, label = CAT_STYLE[ev["category"]]
    if idx in images:
        return f'<img src="{images[idx]}" alt="">'
    return f'<div class="ph" style="background:{color}"><span>{escape(label)}</span></div>'


def _meta(ev: dict, hero: bool = False) -> str:
    bits = []
    if (o := _org_line(ev)):
        bits.append(f"<b>{escape(o)}</b>")
    if hero and (l := _lpr(ev)):
        bits.append(escape(_cut(l, 70)))
    fin = ev.get("finance") or {}
    if fin.get("potential_year"):
        bits.append("Потенциал " + escape(ev.get("fin_effect_text") or "")[:90])
    elif hero:
        bits.append("Потенциал: н/д (численность не указана)")
    if hero and ev.get("business_opportunity"):
        bits.append("Для Сбера: " + escape(_cut(ev["business_opportunity"], 100)))
    chan = (ev.get("channels") or [""])[0]
    url = (ev.get("source_urls") or [""])[0]
    if chan and url.startswith("https://t.me/"):
        bits.append(f'<a href="{escape(url)}">t.me/{escape(chan)}</a>')
    return "<br>".join(bits)


def pick_top(events: list[dict], min_score: int = 3, n: int = MAX_NEWS) -> list[dict]:
    """Главные новости: по убыванию оценки, при равенстве — сначала те, у которых есть фото."""
    pool = [e for e in events if e["relevance_score"] >= min_score]
    return sorted(pool, key=lambda e: (-e["relevance_score"], not e.get("image_url")))[:n]


def build_html(top: list[dict], total_events: int, since: datetime, until: datetime,
               images: dict[int, str], tz: str = "Europe/Moscow") -> str:
    z = ZoneInfo(tz)
    period = f"{since.astimezone(z):%d.%m %H:%M} – {until.astimezone(z):%d.%m.%Y %H:%M} МСК"
    cats: dict[int, int] = {}
    for e in top:
        cats[e["category"]] = cats.get(e["category"], 0) + 1
    chips = "".join(f'<span class="chip">{escape(CAT_STYLE[c][1])} · {n}</span>' for c, n in sorted(cats.items()))
    channels = len({ch for e in top for ch in (e.get("channels") or [])})

    hero, rest = top[0], top[1:]
    hc, hl = CAT_STYLE[hero["category"]]
    hero_html = f"""
    <div class="hero"><table><tr>
      <td class="pic">{_pic(hero, 0, images)}</td>
      <td class="body"><div class="clip" style="height:58mm">
        <span class="tag" style="background:{hc}">{escape(hl)}</span><span class="stars">{_stars(hero['relevance_score'])}</span>
        <h2>{escape(_cut(hero['title'], 100))}</h2>
        <div class="sum">{escape(_cut(hero['summary'], 260))}</div>
        <div class="meta" style="margin-top:2mm">{_meta(hero, hero=True)}</div>
      </div></td></tr></table></div>"""

    cells = []
    for k, ev in enumerate(rest, start=1):
        c, label = CAT_STYLE[ev["category"]]
        cells.append(f"""
        <td><div class="card"><table><tr>
          <td class="pic">{_pic(ev, k, images)}</td>
          <td class="txt"><div class="clip" style="height:43.5mm">
            <span class="tag" style="background:{c}">{escape(label)}</span><span class="stars">{_stars(ev['relevance_score'])}</span>
            <h3>{escape(_cut(ev['title'], 72))}</h3>
            <div class="sum">{escape(_cut(ev['summary'], 105))}</div>
            <div class="meta">{_meta(ev)}</div>
          </div></td></tr></table></div></td>""")
    if len(cells) % 2:
        cells.append("<td></td>")
    rows = "".join(f"<tr>{cells[i]}{cells[i + 1]}</tr>" for i in range(0, len(cells), 2))
    grid = f'<table class="cards">{rows}</table>' if rows else ""

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Радар ЛНР — главное</title>
<style>{CSS}</style></head><body>
<div class="head"><h1>РАДАР ЛНР · ГЛАВНОЕ</h1>
  <div class="sub">{escape(period)} · главных новостей: {len(top)} из {total_events} · источников: {channels} кан.</div>
  <div class="chips">{chips}</div></div>
{hero_html}{grid}
<div class="foot">★ — оценка важности для Сбера (1–5). «≈» — оценочные значения; «н/д» — данных в источнике нет. ИНН и ЛПР —
из реестра DaData или из текста новости; «требует проверки» — организация не определена однозначно. Фото — из исходных
постов публичных Telegram-каналов. Сформировано {datetime.now(z):%d.%m.%Y %H:%M} МСК.</div>
</body></html>"""


def render_pdf(html: str) -> tuple[bytes, int]:
    """HTML -> (PDF в байтах, число страниц)."""
    from weasyprint import HTML
    doc = HTML(string=html).render()
    return doc.write_pdf(), len(doc.pages)


async def make_onepager(events: list[dict], since: datetime, until: datetime, out_dir: Path,
                        min_score: int = 3, tz: str = "Europe/Moscow") -> Path | None:
    """Собирает PDF на одну страницу. Если не влезает — убирает карточки с конца. Нет главных новостей — None."""
    top = pick_top(events, min_score)
    if not top:
        return None
    images_all = await fetch_images(top)
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in range(len(top), 0, -1):
        cut = top[:n]
        html = build_html(cut, len([e for e in events if e["relevance_score"] >= min_score]), since, until,
                          {i: im for i, im in images_all.items() if i < n}, tz)
        pdf, pages = render_pdf(html)
        if pages == 1:
            path = out_dir / f"radar_lnr_{until.astimezone(ZoneInfo(tz)):%Y%m%d_%H%M}_glavnoe.pdf"
            path.write_bytes(pdf)
            return path
        log.warning("PDF не влез на 1 страницу (%d новостей, %d стр.) — уменьшаю", n, pages)
    return None
