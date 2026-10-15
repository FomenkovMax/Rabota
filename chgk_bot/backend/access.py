"""Кто может играть: админ, список ID или участник разрешённой группы (проверяем у Telegram через getChatMember).
Правило то же, что у бота: если ALLOWED_IDS и ALLOWED_CHATS пусты — доступ открыт всем."""
import logging
import time

import httpx

from .settings import Settings

log = logging.getLogger("backend.access")
MEMBER_STATUSES = {"creator", "administrator", "member"}


class AccessChecker:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None, ttl: float = 300):
        self.s = settings
        self.http = http or httpx.AsyncClient(timeout=8)
        self.ttl = ttl
        self._cache: dict[int, tuple[bool, float]] = {}

    @property
    def restricted(self) -> bool:
        return bool(self.s.allowed_ids or self.s.allowed_chats)

    async def allowed(self, user_id: int) -> bool:
        if user_id == self.s.admin_id or not self.restricted or user_id in self.s.allowed_ids:
            return True
        hit = self._cache.get(user_id)
        if hit and hit[1] > time.time():
            return hit[0]
        ok = False
        for chat_id in self.s.allowed_chats:
            if await self._is_member(chat_id, user_id):
                ok = True
                break
        # отказ кэшируем недолго: человека могли только что добавить в группу
        self._cache[user_id] = (ok, time.time() + (self.ttl if ok else 30))
        return ok

    async def _is_member(self, chat_id: int, user_id: int) -> bool:
        try:
            r = await self.http.get(
                f"https://api.telegram.org/bot{self.s.bot_token}/getChatMember",
                params={"chat_id": chat_id, "user_id": user_id},
            )
            data = r.json()
        except Exception:
            log.exception("getChatMember не удался")
            return False
        if not data.get("ok"):
            return False
        m = data["result"]
        return m.get("status") in MEMBER_STATUSES or (m.get("status") == "restricted" and m.get("is_member"))
