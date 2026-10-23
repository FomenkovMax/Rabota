"""Поиск КАНДИДАТОВ продуктовых страниц на официальном сайте.

Результат — только список для ручной проверки. В config/sources.yaml и в статус
active ничего не попадает автоматически.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

KEYWORDS = {
    "deposit": ("вклад", "deposit"),
    "savings": ("накопител", "savings"),
    "promo": ("акци", "promo", "спецпредлож"),
}


@dataclass(frozen=True)
class Candidate:
    category: str
    url: str
    anchor: str


def _strip_tracking(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
    return urlunparse(p._replace(query=urlencode(q)))


def discover_links(html: bytes, base_url: str, official_hosts: set[str]) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        url = _strip_tracking(urldefrag(urljoin(base_url, a["href"]))[0])
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme not in ("http", "https") or not any(host == h or host.endswith("." + h) for h in official_hosts):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        haystack = f"{text} {parsed.path}".lower()
        for category, words in KEYWORDS.items():
            if any(w in haystack for w in words) and url not in seen:
                seen.add(url)
                out.append(Candidate(category, url, text[:120]))
                break
    return out
