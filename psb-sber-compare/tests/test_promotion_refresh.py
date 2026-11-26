
from datetime import datetime, timedelta
import json

from src import current_offers, promotion_refresh, reviewed_offers
from src.pipeline import Config


NOW = datetime(2026, 11, 25, 16, tzinfo=current_offers.MOSCOW)
BANK = "Сбер"
HUB = "https://bank.example/promos"
RULES = "https://bank.example/rules.pdf"
CITY = "https://bank.example/offices"
NEW = "https://bank.example/promo/new"
OTHER = "https://bank.example/promo/other"
ROW = {
    "bank": BANK, "title": "Акция «Бонус»", "rules": RULES, "regional_source": CITY,
    "text": ("Акция действует с 01.11.2026 по 30.11.2026 включительно. "
             "Акция действует в Луганске. Условия участия: оформите вклад."),
    "checked_at": (NOW - timedelta(days=2)).isoformat(),
}


def _config(tmp_path):
    evidence = tmp_path / "evidence.json"
    profile = tmp_path / "profile.json"
    evidence.write_text(json.dumps({"tariffs": [], "promotions": [ROW]}), encoding="utf-8")
    profile.write_text(json.dumps({
        "banks": {BANK: [HUB]},
        "rules": {RULES: {"sha256": "original", "geography": [{"url": CITY, "contains": ["офис в Луганске"]}]}},
    }), encoding="utf-8")
    return Config({"reviewed_offers": str(evidence), "promotion_refresh": {
        "sources": str(profile), "state": str(tmp_path / "state.json")}})


def _read(config, now):
    _, _, promos = reviewed_offers.load(config.path("reviewed_offers"), {BANK}, now.date(),
                                       state_path=config.path("promotion_refresh", "state"))
    return [p.title for p in promos if current_offers.active_promo(p, region="lugansk", now=now, hours=24)]


def _html(text):
    return promotion_refresh.Document("html", page=promotion_refresh.Page(text))


def test_live_confirmation_needs_unchanged_rules_and_city_proof(tmp_path):
    config = _config(tmp_path)
    documents = {RULES: promotion_refresh.Document("pdf", "original"),
                 CITY: _html("<p>Офис в Луганске</p>"), HUB: _html("<h1>Предложения</h1>")}
    assert _read(config, NOW) == []
    state = promotion_refresh.run(config, fetch_document=documents.__getitem__, now=NOW)
    assert state["checks"][RULES]["status"] == "confirmed"
    assert _read(config, NOW) == [ROW["title"]]

    documents[CITY] = promotion_refresh.Document("unavailable")
    retry = NOW + timedelta(hours=3)
    state = promotion_refresh.run(config, fetch_document=documents.__getitem__, now=retry)
    assert state["checks"][RULES]["checked_at"] == NOW.isoformat()
    assert _read(config, retry) == [ROW["title"]]
    assert not _read(config, NOW + timedelta(hours=25))

    documents[RULES] = promotion_refresh.Document("pdf", "updated")
    state = promotion_refresh.run(config, fetch_document=documents.__getitem__, now=retry)
    assert state["checks"][RULES]["status"] == "changed"
    assert not _read(config, retry)
    documents[RULES] = promotion_refresh.Document("unavailable")
    promotion_refresh.run(config, fetch_document=documents.__getitem__, now=retry)
    assert not _read(config, retry)


def test_expired_and_automatically_discovered_promotions_are_filtered(tmp_path):
    config = _config(tmp_path)
    documents = {
        RULES: promotion_refresh.Document("pdf", "original"),
        CITY: _html("<p>Офис в Луганске</p>"),
        HUB: _html('<a href="/promo/new">Акция</a><a href="/promo/other">Акция</a>'),
        NEW: _html("""<h1>Акция «Новая»</h1><p>Акция действует с 01.11.2026 по 10.12.2026.</p>
                   <p>Территория проведения акции: г. Луганск.</p><p>Условия участия: оформите дебетовую карту.</p>"""),
        OTHER: _html("""<h1>Акция «Общая»</h1><p>Акция действует с 01.11.2026 по 10.12.2026.</p>
                     <p>Территория проведения акции: Российская Федерация.</p><p>Офисы в Луганске.</p>
                     <p>Условия участия: оформите дебетовую карту.</p>"""),
    }
    later = datetime(2026, 12, 1, 12, tzinfo=current_offers.MOSCOW)
    state = promotion_refresh.run(config, fetch_document=documents.__getitem__, now=later)
    assert state["checks"][RULES]["status"] == "expired"
    assert _read(config, later) == ["Акция «Новая»"]
