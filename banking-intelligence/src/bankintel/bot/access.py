from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AllowlistMiddleware(BaseMiddleware):
    """Пускает только пользователей из ALLOWED_TELEGRAM_IDS. Пустой список = никого."""

    def __init__(self, allowed_ids: list[int]):
        self.allowed = set(allowed_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self.allowed:
            if isinstance(event, Message):
                await event.answer("Доступ закрыт. Попросите администратора добавить ваш Telegram ID.")
            return None
        return await handler(event, data)
