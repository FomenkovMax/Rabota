from datetime import datetime, timezone
from pathlib import Path

from radar.sources.tme_web import parse_channel_html

HTML = (Path(__file__).parent / "fixtures" / "tme_sample.html").read_text(encoding="utf-8")


def test_parse_extracts_posts():
    posts = parse_channel_html(HTML, "government_lnr")
    assert len(posts) >= 5
    p = posts[0]
    assert p.channel == "government_lnr"
    assert p.url == f"https://t.me/government_lnr/{p.post_id}"
    assert p.text and p.published_at.tzinfo is not None


def test_known_post_text_and_date():
    posts = {p.post_id: p for p in parse_channel_html(HTML, "government_lnr")}
    p = posts[59158]
    assert "Юношеская сборная ЛНР победила" in p.text
    assert p.published_at == datetime(2026, 10, 8, 8, 31, 20, tzinfo=timezone.utc)


def test_empty_page_gives_no_posts():
    assert parse_channel_html("<html><body>nothing</body></html>", "x") == []
