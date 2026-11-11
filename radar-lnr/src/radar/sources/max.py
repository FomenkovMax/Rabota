"""Фаза 2 (НЕ реализовано): MAX https://max.ru/government_lnr. Заглушка интерфейса."""
from .base import Post, Source


class MaxSource(Source):
    name = "max"

    async def fetch(self, channel: str, since):  # pragma: no cover
        raise NotImplementedError("MAX — Фаза 2")
