"""Отправка сообщений с учётом лимитов Telegram и блокировок бота."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile

log = logging.getLogger(__name__)
PAUSE_S = 0.6  # между сообщениями (лимит Telegram: ~1 сообщение/сек в один чат, ~30/сек всего)


def is_quiet(hour: int, quiet: list[int] | None) -> bool:
    """Тихие часы [с, до) по кругу: [23, 7] — с 23:00 до 07:00. Пусто/None — тихих часов нет."""
    if not quiet or len(quiet) != 2 or quiet[0] == quiet[1]:
        return False
    start, end = quiet
    return start <= hour < end if start < end else (hour >= start or hour < end)


def recipients(chat_ids: list[int], allowed: set[int], muted: set[int]) -> list[int]:
    """Группа/чаты из DIGEST_CHAT_IDS + личка каждому из whitelist, кто не нажал /mute."""
    out: list[int] = []
    for cid in [*chat_ids, *sorted(allowed)]:
        if cid in muted and cid > 0:      # /mute действует только на личные чаты
            continue
        if cid not in out:
            out.append(cid)
    return out


async def safe_send(bot: Bot, chat_id: int, text: str, files: list[Path] | None = None,
                    disable_preview: bool = True, silent: bool = False) -> bool:
    """True если доставлено. «Бот заблокирован» и прочие ошибки не роняют рассылку."""
    for attempt in range(3):
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=disable_preview, disable_notification=silent)
            for f in files or []:
                await bot.send_document(chat_id, FSInputFile(f), disable_notification=silent)
                await asyncio.sleep(PAUSE_S)
            return True
        except TelegramRetryAfter as e:
            log.warning("flood control, ждём %sс", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            log.warning("чат %s: бот заблокирован или не добавлен — пропускаем", chat_id)
            return False
        except TelegramAPIError as e:
            log.error("чат %s: ошибка Telegram: %s", chat_id, e)
            return False
    return False


async def broadcast(bot: Bot, chats: list[int], text: str, files: list[Path] | None = None,
                    silent: bool = False) -> dict[int, bool]:
    result = {}
    for cid in chats:
        result[cid] = await safe_send(bot, cid, text, files, silent=silent)
        await asyncio.sleep(PAUSE_S)
    return result
