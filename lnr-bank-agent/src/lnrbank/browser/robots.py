"""Соблюдение robots.txt (D-7). Недоступный robots.txt не запрещает обход."""

from __future__ import annotations

import logging
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)


class RobotsGate:
    def __init__(self, fetch: Callable[[str], str], user_agent: str = "*") -> None:
        self.fetch = fetch
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            try:
                parser = RobotFileParser()
                parser.parse(self.fetch(f"{origin}/robots.txt").splitlines())
                self._parsers[origin] = parser
            except Exception as exc:  # noqa: BLE001 — нет robots.txt значит нет запретов
                log.info("robots.txt %s недоступен: %s", origin, exc)
                self._parsers[origin] = None
        parser = self._parsers[origin]
        return parser is None or parser.can_fetch(self.user_agent, url)
