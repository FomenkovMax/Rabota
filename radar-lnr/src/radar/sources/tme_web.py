"""Парсер публичного превью https://t.me/s/<username> (без авторизации)."""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .base import Post, Source

log = logging.getLogger(__name__)


class ChannelUnavailable(Exception):
    """Канал нельзя прочитать через веб-превью (приватный, нет превью, 404 и т.п.)."""


_BG_URL = re.compile(r"background-image:\s*url\(['\"]?([^'\")]+)['\"]?\)")


def _first_image(msg) -> str | None:
    """Первое фото/превью видео поста (CSS background-image) — только https-адрес."""
    for sel in ("a.tgme_widget_message_photo_wrap", "i.tgme_widget_message_video_thumb",
                "a.tgme_widget_message_link_preview i.link_preview_image"):
        node = msg.css_first(sel)
        if node and (m := _BG_URL.search(node.attributes.get("style") or "")):
            url = m.group(1)
            if url.startswith("https://"):
                return url
    return None


def parse_channel_html(html: str, channel: str) -> list[Post]:
    """Чистая функция: HTML страницы -> список постов. Удобно тестировать на сохранённой фикстуре."""
    tree = HTMLParser(html)
    posts: list[Post] = []
    for msg in tree.css("div.tgme_widget_message"):
        data_post = msg.attributes.get("data-post")  # 'username/12345'
        if not data_post or "/" not in data_post:
            continue
        try:
            post_id = int(data_post.rsplit("/", 1)[1])
        except ValueError:
            continue
        # У поста бывает вложенный div с тем же классом — берём первый (внешний)
        text_node = msg.css_first("div.tgme_widget_message_text")
        text = text_node.text(separator="\n", strip=True) if text_node else ""
        time_node = msg.css_first("a.tgme_widget_message_date time")
        if not text or not time_node or not time_node.attributes.get("datetime"):
            continue  # посты без текста (только фото/видео) нам не нужны
        published = datetime.fromisoformat(time_node.attributes["datetime"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        posts.append(Post(channel=channel, post_id=post_id, url=f"https://t.me/{channel}/{post_id}",
                          text=text, published_at=published.astimezone(timezone.utc), image_url=_first_image(msg)))
    return posts


class TmeWebSource(Source):
    name = "tme_web"

    def __init__(self, cfg: dict, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self.client = client or httpx.AsyncClient(
            timeout=cfg["timeout_s"], headers={"User-Agent": cfg["user_agent"], "Accept-Language": "ru,en;q=0.8"},
            follow_redirects=False)  # редирект на t.me/<name> = у канала нет превью

    async def _get(self, url: str) -> httpx.Response:
        """GET с ретраями и экспоненциальным backoff (2с, 4с, 8с...)."""
        last: Exception | None = None
        for attempt in range(self.cfg["retries"]):
            try:
                r = await self.client.get(url)
                if r.status_code in (429, 500, 502, 503, 504):
                    wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                    log.warning("HTTP %s от %s, ждём %sс", r.status_code, url, wait)
                    await asyncio.sleep(min(wait, 60))
                    continue
                return r
            except httpx.HTTPError as e:
                last = e
                await asyncio.sleep(2 ** (attempt + 1))
        raise ChannelUnavailable(f"сеть/таймаут: {last or 'повторные ошибки сервера'}")

    async def fetch(self, channel: str, since: datetime) -> list[Post]:
        r = await self._get(f"https://t.me/s/{channel}")
        if r.status_code in (301, 302, 303, 307, 308):
            raise ChannelUnavailable("нет веб-превью (редирект) — канал закрыт или это не канал")
        if r.status_code != 200:
            raise ChannelUnavailable(f"HTTP {r.status_code}")
        if "tgme_widget_message" not in r.text:
            raise ChannelUnavailable("в странице нет постов (пустой канал или превью отключено)")
        posts = parse_channel_html(r.text, channel)
        posts = [p for p in posts if p.published_at > since]
        posts.sort(key=lambda p: p.post_id, reverse=True)
        return posts[: self.cfg["max_posts_per_channel"]]

    async def polite_pause(self) -> None:
        await asyncio.sleep(random.uniform(self.cfg["delay_min_s"], self.cfg["delay_max_s"]))

    async def aclose(self) -> None:
        await self.client.aclose()
