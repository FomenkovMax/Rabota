import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from radar.report.pdf import build_html, fetch_images, make_onepager, pick_top, render_pdf
from radar.sources.tme_web import parse_channel_html

NOW = datetime.now(timezone.utc)
LONG = "Очень длинный текст новости про организацию и её решения. " * 12


def ev(i, score=4, cat=1, **kw):
    base = {"category": cat, "title": f"Новость номер {i} " + LONG[:140], "summary": LONG, "relevance_score": score,
            "organizations": [{"name": "ООО «Ромашка и компания очень длинное название»", "inn_if_in_text": None}],
            "persons": [{"name": "Иван Иванов", "position": "директор"}], "source_urls": [f"https://t.me/chan/{i}"],
            "channels": ["chan"], "business_opportunity": LONG[:300]}
    return {**base, **kw}


def test_pick_top_orders_by_score_then_photo_and_filters():
    events = [ev(1, 3), ev(2, 5), ev(3, 5, image_url="https://cdn1.telesco.pe/x.jpg"), ev(4, 2), ev(5, 4)]
    top = pick_top(events, min_score=3)
    assert [e["relevance_score"] for e in top] == [5, 5, 4, 3]
    assert top[0].get("image_url")                      # при равной оценке сначала новость с фото
    assert pick_top([ev(1, 2)], min_score=3) == []


def test_pdf_is_exactly_one_page_even_with_max_news_and_long_texts():
    top = [ev(i, 5 - i % 3, cat=1 + i % 8) for i in range(7)]
    pdf, pages = render_pdf(build_html(top, 20, NOW - timedelta(hours=4), NOW, {}))
    assert pdf[:4] == b"%PDF" and pages == 1


def test_pdf_html_escapes_untrusted_text():
    e = ev(1, title="<script>alert(1)</script> & <b>x</b>", summary="<img src=x onerror=alert(1)>")
    html = build_html([e], 1, NOW - timedelta(hours=4), NOW, {})
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "<img src=x" not in html


def test_make_onepager_none_without_top_news_and_creates_file(tmp_path):
    assert asyncio.run(make_onepager([ev(1, 2)], NOW - timedelta(hours=4), NOW, tmp_path)) is None
    path = asyncio.run(make_onepager([ev(i) for i in range(9)], NOW - timedelta(hours=4), NOW, tmp_path))
    assert path and path.suffix == ".pdf" and path.read_bytes()[:4] == b"%PDF"


def test_fetch_images_allows_only_telegram_cdn_and_converts_to_jpeg():
    import io
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, content=buf.getvalue())

    events = [ev(1, image_url="https://cdn4.telesco.pe/file/a.jpg"),
              ev(2, image_url="https://evil.example.com/a.jpg"),         # чужой хост — не качаем
              ev(3, image_url="http://cdn4.telesco.pe/file/b.jpg"),       # не https — не качаем
              ev(4)]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = asyncio.run(fetch_images(events, client))
    assert list(out) == [0] and out[0].startswith("data:image/jpeg;base64,") and len(seen) == 1


def test_parser_extracts_photo_url_https_only():
    html = ('<div class="tgme_widget_message" data-post="c/1"><a class="tgme_widget_message_photo_wrap" '
            'style="background-image:url(\'https://cdn1.telesco.pe/file/p.jpg\')" href="x"></a>'
            '<div class="tgme_widget_message_text">текст</div>'
            '<a class="tgme_widget_message_date"><time datetime="2026-01-01T00:00:00+00:00"></time></a></div>')
    posts = parse_channel_html(html, "c")
    assert posts and posts[0].image_url == "https://cdn1.telesco.pe/file/p.jpg"
