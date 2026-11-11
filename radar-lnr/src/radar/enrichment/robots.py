"""Проверка robots.txt перед парсингом сайтов (companium.ru, bus.gov.ru). Закрыто по умолчанию."""
from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


async def can_fetch(url: str, user_agent: str, client: httpx.AsyncClient | None = None) -> bool:
    """True только если robots.txt прочитан и разрешает. Не удалось прочитать — считаем «нельзя»."""
    p = urlparse(url)
    own = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": user_agent})
    try:
        r = await own.get(f"{p.scheme}://{p.netloc}/robots.txt")
        if r.status_code != 200:
            return False
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(user_agent, url)
    except httpx.HTTPError:
        return False
    finally:
        if client is None:
            await own.aclose()
