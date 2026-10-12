"""Запасной источник через Telethon (отдельный пользовательский аккаунт). Включается USE_TELETHON=true.

Не реализован полностью: интерфейс заложен, основной способ — веб-превью t.me/s.
"""
from .base import Source


class TelethonSource(Source):
    name = "telethon"

    async def fetch(self, channel: str, since):  # pragma: no cover
        raise NotImplementedError("Telethon-режим пока не реализован (нужны TELETHON_API_ID/HASH и сессия)")
