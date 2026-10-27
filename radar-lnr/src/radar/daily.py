"""Ежедневная рассылка: что накопилось с прошлой отправки -> шапка + файлы + карточки с кнопками оценки."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from .db import DB
from .llm.schemas import CATEGORIES
from .report.digest import _fmt_event, usage_line
from .report.feedback import vote_caption, vote_rows


def pick_events(events: list[dict], min_score: int, max_cards: int) -> tuple[list[dict], list[dict]]:
    """(карточки, остальные от dashboard-порога). Карточки: от min_score звёзд, лучшие первыми, не больше max_cards."""
    ranked = sorted(events, key=lambda e: (-e["relevance_score"], e.get("category", 0), e["id"]))
    cards = [e for e in ranked if e["relevance_score"] >= min_score][:max_cards]
    return cards, [e for e in ranked if e not in cards]


def header_text(cards: list[dict], total: int, since: datetime, until: datetime, tz: str, failed: int,
                tokens_line: str, min_score: int) -> str:
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz)
    head = f"📡 <b>Радар ЛНР</b> · итоги дня · {since.astimezone(z):%d.%m %H:%M} – {until.astimezone(z):%d.%m %H:%M}"
    if cards:
        cnt: dict[int, int] = {}
        for e in cards:
            cnt[e["category"]] = cnt.get(e["category"], 0) + 1
        head += f"\nНовостей от {min_score}⭐: {len(cards)} · " + " ".join(f"{CATEGORIES[c][0]}{n}" for c, n in sorted(cnt.items()))
        head += "\n👇 Под каждой новостью оцени полезность 1–5 — по оценкам настраиваем звёзды."
    else:
        head += f"\nЗначимых новостей (от {min_score}⭐) за период нет."
    if total > len(cards):
        head += f"\nВсего за период: {total} — остальные в приложенных HTML/Excel."
    if failed:
        head += f"\n⚠️ не читаются каналов: {failed}"
    if tokens_line:
        head += "\n" + tokens_line
    return head


def card_text(ev: dict, avg: float | None = None, n: int = 0, mine: int | None = None) -> str:
    return f"⭐{ev['relevance_score']} " + _fmt_event(ev) + "\n\n<i>" + escape(vote_caption(avg, n, mine)) + "</i>"


def keyboard(event_id: int, mine: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)
                                                  for t, d in row] for row in vote_rows(event_id, mine)])


def tokens_line_for_day(db: DB, left: int | None, warn: int | None) -> str:
    since = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat(timespec="seconds")
    return usage_line(db.spent_since(since), left, False, warn)


async def send_cards(bot: Bot, chats: list[int], cards: list[dict], silent: bool = False) -> int:
    """Карточки каждому получателю; возвращает число успешных отправок. Ошибка одного чата не мешает остальным."""
    import asyncio
    from aiogram.exceptions import TelegramAPIError
    ok = 0
    for cid in chats:
        for ev in cards:
            try:
                await bot.send_message(cid, card_text(ev), reply_markup=keyboard(ev["id"]),
                                       disable_web_page_preview=True, disable_notification=True)
                ok += 1
            except TelegramAPIError:
                break            # чат недоступен — остальные карточки туда не пробуем
            await asyncio.sleep(0.6)
    return ok
