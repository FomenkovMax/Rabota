"""Фаза 2 (НЕ реализовано): VK https://vk.com/public213550036. Заглушка интерфейса."""
from .base import Post, Source


class VKSource(Source):
    name = "vk"

    async def fetch(self, channel: str, since):  # pragma: no cover
        raise NotImplementedError("VK — Фаза 2")
