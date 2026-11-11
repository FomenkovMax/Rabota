"""Доступ только для whitelist (ALLOWED_USER_IDS). Остальным — вежливый отказ + запись в лог."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

log = logging.getLogger(__name__)

# Команды, доступные всем (чтобы коллега мог прислать свой ID)
PUBLIC_COMMANDS = {"/myid"}
# Команды, которыми могут пользоваться ВСЕ участники группы дайджеста (членством в группе управляет админ).
# Тратящие токены (/digest) и платные запросы (/inn) сюда не входят.
GROUP_COMMANDS = {"/start", "/help", "/menu", "/myid", "/chatid", "/report", "/stats", "/channels"}


def is_allowed(user_id: int | None, allowed: set[int]) -> bool:
    return user_id is not None and user_id in allowed


def command_of(text: str | None) -> str:
    """'/myid@bot arg' -> '/myid'."""
    return (text or "").split()[0].split("@")[0].lower() if text else ""


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, allowed: set[int], group_ids: set[int] | None = None):
        self.allowed = allowed
        self.group_ids = {g for g in (group_ids or set()) if g < 0}     # только группы (отрицательные id)

    async def __call__(self, handler: Callable[[Message, dict], Awaitable[Any]], event: Message, data: dict):
        uid = event.from_user.id if event.from_user else None
        cmd = command_of(event.text)
        in_group_chat = event.chat is not None and event.chat.id in self.group_ids
        if cmd in PUBLIC_COMMANDS or is_allowed(uid, self.allowed) or (in_group_chat and cmd in GROUP_COMMANDS):
            return await handler(event, data)
        log.warning("Отказ в доступе: user_id=%s username=%s text=%r", uid,
                    event.from_user.username if event.from_user else None, (event.text or "")[:50])
        await event.answer("Извините, доступ к боту ограничен. Чтобы получить доступ, "
                           "отправьте администратору свой ID (команда /myid).")
        return None
