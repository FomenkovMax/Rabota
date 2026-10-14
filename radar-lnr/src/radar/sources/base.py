"""Общий интерфейс источника. Фаза 2 (VK, MAX) просто добавит новые классы с тем же методом fetch."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Post:
    channel: str            # username канала (или id источника)
    post_id: int
    url: str
    text: str
    published_at: datetime  # всегда с таймзоной (UTC)
    source: str = "telegram"
    image_url: str | None = None   # фото из превью поста (для визуала в PDF), если есть


class Source(ABC):
    """Источник постов. fetch() возвращает посты канала новее `since`."""

    name: str

    @abstractmethod
    async def fetch(self, channel: str, since: datetime) -> list[Post]:
        ...
