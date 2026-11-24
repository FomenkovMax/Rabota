
"""Refresh live confirmation of retail promotions without a catalogue crawl."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urljoin, urlsplit

import requests

from . import current_offers, reviewed_offers
from .psb.client import build_ca_bundle

log = logging.getLogger(__name__)
MAX_BYTES = 7_000_000
PROMO_LINK = re.compile(r"/(?:promo|promotions|akcii|aktsii|savingsoffers)/|\b(?:акци[яиюй]|розыгрыш)\b", re.I)
EXPLICIT_CITY = re.compile(
    r"^(?:территория(?: проведения)? акции|акция действует)[: —–]*(?:в |на территории )?"
    r"(?:г\.?\s*|город[е]?\s+)?Луганск[е]?\.?$", re.I | re.M
)
PARTICIPATION = re.compile(r"^(?:условия участия|для участия)\s*[:—–-]\s*([^\n]{12,550})$", re.I | re.M)
PERIOD = re.compile(r"^Акция действует с \d{2}\.\d{2}\.\d{4} (?:по|до) \d{2}\.\d{2}\.\d{4}(?: включительно)?\.?$", re.I | re.M)


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.parts, self.heading, self.links = [], [], []
        self.in_heading = False
        self.ignored = None
        self.link = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.ignored = tag
        elif not self.ignored and tag == "a":
            self.link = (dict(attrs).get("href") or "", [])
        elif not self.ignored and tag == "h1":
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None
        if self.ignored:
            return
        if tag == "h1":
            self.in_heading = False
        if tag == "a" and self.link:
            href, labels = self.link
            self.links.append((href, " ".join(labels)))
            self.link = None
        if tag in {"p", "div", "li", "h1", "h2", "h3", "section", "br"}:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.ignored:
            return
        part = " ".join(data.split())
        if part:
            self.parts.append(part)
            if self.in_heading:
                self.heading.append(part)
            if self.link:
                self.link[1].append(part)

    @property
    def text(self):
        return "\n".join(" ".join(line.split()) for line in " ".join(self.parts).splitlines()
                         if line.strip())


@dataclass
class Document:
    status: str
    digest: str = ""
    page: Page | None = None


def fetch(url, ca):
    started = time.monotonic()
    try:
        with requests.get(url, verify=ca, timeout=(7, 15), stream=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as response:
            if response.status_code in {404, 410}:
                return Document("removed")
            response.raise_for_status()
            if urlsplit(response.url).scheme != "https" or official_host(response.url) != official_host(url):
                return Document("unavailable")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    return Document("unavailable")
                if time.monotonic() - started > 30:
                    return Document("unavailable")
    except requests.RequestException:
        return Document("unavailable")
    if body.startswith(b"%PDF"):
        return Document("pdf", digest=sha256(body).hexdigest())
    page = Page(body.decode("utf-8", errors="replace"))
    if len(page.text) < 150:
        return Document("unavailable")
    return Document("html", page=page)


def fetch_all(urls, fetch_document):
    with ThreadPoolExecutor(max_workers=8) as workers:
        return dict(zip(urls, workers.map(fetch_document, urls)))


def region_matches(document, phrases):
    if document.status != "html":
        return False
    text = " ".join(document.page.text.casefold().split())
    return all(phrase.casefold() in text for phrase in phrases)


def check_known(row, profile, documents, now):
    promo = reviewed_offers.promotion(row, now.date())
    if promo is None:
        return "changed"
    promo.checked_at = now.isoformat()
    if not current_offers.active_promo(promo, region="lugansk", now=now, hours=24):
        return "expired"
    rules = documents[row["rules"]]
    if rules.status == "removed" or (rules.status == "pdf" and rules.digest != profile["sha256"]):
        return "changed"
    if rules.status != "pdf":
        return "unavailable"
    geography = profile.get("geography", ())
    if geography and not any(region_matches(documents[item["url"]], item["contains"]) for item in geography):
        return "unavailable"
    return "confirmed"


def official_host(url):
    hostname = urlsplit(url).hostname or ""
    return hostname.removeprefix("www.")


def candidate_urls(bank_hubs, documents):
    candidates = {}
    hosts = {official_host(url) for url in bank_hubs if official_host(url) != "t.me"}
    for hub in bank_hubs:
        doc = documents[hub]
        if doc.page is None:
            continue
        for href, label in doc.page.links:
            try:
                url = urljoin(hub, href).split("#", 1)[0]
                parts = urlsplit(url)
            except ValueError:
                continue
            if (parts.scheme == "https" and official_host(url) in hosts and url not in bank_hubs
                    and PROMO_LINK.search(f"{parts.path} {label}")):
                candidates.setdefault(url, label[:150])
    return candidates


def explicit_promo(bank, url, document, now):
    if document.page is None or official_host(url) == "t.me":
        return None
    page = document.page
    title = " ".join(page.heading)
    if not title or len(title) > 150 or not re.search(r"акци[яиюй]|розыгрыш|кешбэк", title, re.I):
        return None
    text = page.text
    period, city, participation = PERIOD.search(text), EXPLICIT_CITY.search(text), PARTICIPATION.search(text)
    if not all((period, city, participation)):
        return None
    row = {"bank": bank, "title": title, "rules": url, "regional_source": url,
           "checked_at": now.isoformat(),
           "text": f"{period[0].rstrip('.')}. Акция действует в Луганске. Условия участия: {participation[1]}"}
    promo = reviewed_offers.promotion(row, now.date())
    if promo and current_offers.active_promo(promo, region="lugansk", now=now, hours=24):
        return row
    return None


def run(config, *, fetch_document=None, now=None):
    now = now or datetime.now(current_offers.MOSCOW)
    batch = json.loads(config.path("reviewed_offers").read_text(encoding="utf-8"))
    profile = json.loads(config.path("promotion_refresh", "sources").read_text(encoding="utf-8"))
    path = config.path("promotion_refresh", "state")
    prior = reviewed_offers.promotion_state(path)
    checked_at = now.isoformat()
    banks = profile["banks"]
    rules = profile["rules"]

    urls = list(dict.fromkeys([*rules,
                               *(proof["url"] for rule in rules.values() for proof in rule.get("geography", ())),
                               *(url for hubs in banks.values() for url in hubs)]))
    if fetch_document is None:
        ca = build_ca_bundle()
        def fetch_document(url):
            return fetch(url, ca)
    try:
        documents = fetch_all(urls, fetch_document)
        checks = {}
        for row in batch["promotions"]:
            url = row["rules"]
            if url not in rules:
                continue
            status = check_known(row, rules[url], documents, now)
            version = reviewed_offers.promotion_version(row)
            last = prior.get("checks", {}).get(url, {})
            effective_date = checked_at if status == "confirmed" else row["checked_at"]
            if status == "unavailable" and last.get("version") == version:
                if last.get("status") == "changed":
                    status = "changed"
                elif last.get("checked_at"):
                    effective_date = last["checked_at"]
            checks[url] = {"bank": row["bank"], "title": row["title"], "version": version,
                           "status": status, "checked_at": effective_date}

        reports = {}
        for bank, hubs in banks.items():
            links = candidate_urls(hubs, documents)
            previous_links = (p["rules"] for p in prior.get("discovered", ()) if p["bank"] == bank)
            candidates = list(dict.fromkeys([*previous_links, *links]))
            candidates = [url for url in candidates if url not in rules][:8]
            reports[bank] = {"sources": {url: documents[url].status for url in hubs},
                             "candidates": [{"url": url, "title": links.get(url, "")} for url in candidates]}
        candidate_links = list(dict.fromkeys(item["url"] for report in reports.values()
                                              for item in report["candidates"]))
        documents.update(fetch_all([url for url in candidate_links if url not in documents], fetch_document))
        discovered = []
        for bank, report in reports.items():
            for item in report["candidates"]:
                url = item["url"]
                document = documents[url]
                item["status"] = document.status
                if row := explicit_promo(bank, url, document, now):
                    discovered.append(row)
        state = {"checked_at": checked_at, "checks": checks, "banks": reports, "discovered": discovered}
        save(path, state)
        for bank, report in reports.items():
            results = [x for x in checks.values() if x["bank"] == bank]
            log.info("%s: источники %s/%s, подтверждено %s/%s, кандидаты %s", bank,
                     sum(v in {"html", "pdf"} for v in report["sources"].values()), len(report["sources"]),
                     sum(x["status"] == "confirmed" for x in results), len(results), len(report["candidates"]))
        return state
    finally:
        if "ca" in locals():
            import certifi
            if ca != certifi.where():
                Path(ca).unlink(missing_ok=True)


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as staging:
        temporary = Path(staging.name)
        try:
            json.dump(state, staging, ensure_ascii=False, indent=2)
            staging.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def watch(config, interval=12 * 3600):
    while True:
        try:
            state = run(config)
        except (OSError, ValueError, KeyError) as exc:
            log.error("Сверка акций не выполнена: %s", exc)
            time.sleep(1800)
        else:
            delay = 2 * 3600 if any(row["status"] == "unavailable" for row in state["checks"].values()) else interval
            time.sleep(delay)
