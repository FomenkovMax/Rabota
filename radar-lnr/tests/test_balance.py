from datetime import datetime, timedelta, timezone

import httpx
import pytest
from test_cross_run_dedup import ParaLLM, PostsSource, mk

from radar.db import DB
from radar.llm.client import LLMAuthError, LLMBalanceError, _explain, fetch_balance
from radar.report.digest import build_digest, usage_line


# ---------------------------------------------------------------- получение баланса
async def test_fetch_balance_parses_and_strips_v1():
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers.get("authorization")))
        return httpx.Response(200, json={"object": "balance", "token_balance": 19431599})

    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await fetch_balance("https://proxy.example/v1", "KEY", client=c) == 19431599
    assert seen[0] == ("https://proxy.example/v1/balance", "Bearer KEY")        # /v1 не задваивается


async def test_fetch_balance_none_when_unsupported_or_broken():
    for resp in (httpx.Response(404), httpx.Response(200, text="not json"), httpx.Response(200, json={"x": 1})):
        c = httpx.AsyncClient(transport=httpx.MockTransport(lambda r, resp=resp: resp))
        assert await fetch_balance("https://p.example", "K", client=c) is None


# ---------------------------------------------------------------- «токены закончились» ≠ «неверный ключ»
def test_out_of_balance_is_recognised():
    assert isinstance(_explain(402, ""), LLMBalanceError)
    assert isinstance(_explain(429, "Insufficient balance"), LLMBalanceError)
    assert isinstance(_explain(403, "недостаточно средств на балансе"), LLMBalanceError)
    assert isinstance(_explain(403, "Forbidden: region"), LLMAuthError)           # гео-блок — по-прежнему ключ/доступ
    assert not isinstance(_explain(429, "rate limit exceeded"), LLMBalanceError)  # обычный лимит частоты


# ---------------------------------------------------------------- строка в конце дайджеста
def test_usage_line_format_and_warning():
    assert usage_line(123456, 19419254) == "🪙 Токенов: потрачено 123 456 / осталось 19 419 254"
    assert usage_line(None, None) == "🪙 Токенов: потрачено н/д / осталось н/д"
    assert "≈1 000" in usage_line(1000, None, approx=True)
    low = usage_line(10, 500, warn_below=1000)
    assert "осталось 500" in low and "мало" in low and "мало" not in usage_line(10, 5000, warn_below=1000)


def test_digest_ends_with_tokens_line_with_and_without_events():
    now = datetime.now(timezone.utc)
    line = usage_line(1000, 2000)
    empty = build_digest([], now - timedelta(hours=4), now, 2, tokens_line=line)
    assert empty.rstrip().endswith("осталось 2 000") and "не удалось прочитать: 2" in empty
    ev = {"category": 1, "title": "t", "summary": "s", "relevance_score": 4, "organizations": [], "source_urls": []}
    full = build_digest([ev], now - timedelta(hours=4), now, 0, tokens_line=line)
    assert full.rstrip().endswith("осталось 2 000") and len(full) < 4096


# ---------------------------------------------------------------- пайплайн
class BalanceLLM(ParaLLM):
    def __init__(self, balances):
        self.balances = list(balances)

    async def get_balance(self):
        return self.balances.pop(0)


def _patch(monkeypatch, pipeline, llm):
    monkeypatch.setattr(pipeline, "make_client", lambda env: llm)
    monkeypatch.setattr(pipeline, "build_adapters", lambda env, cfg: [])
    monkeypatch.setattr(pipeline, "load_channels", lambda: [{"username": "a"}])

    async def no_pdf(*a, **k):
        return None
    monkeypatch.setattr(pipeline, "make_onepager", no_pdf)
    monkeypatch.setattr(pipeline, "export_files", lambda *a, **k: [])


async def test_run_reports_spent_and_left_from_service_balance(tmp_path, monkeypatch):
    from radar import pipeline
    _patch(monkeypatch, pipeline, BalanceLLM([5_000_000, 4_988_500]))
    r = await pipeline.run_once(DB(tmp_path / "t.db"), hours=24, source=PostsSource(
        [mk("a", 1, "В Луганске открылся новый филиал ООО Ромашка: вложено 99 млн рублей в запуск производства")]))
    assert (r.tokens_before, r.tokens_left, r.tokens_spent, r.tokens_approx) == (5_000_000, 4_988_500, 11_500, False)
    assert r.digest.rstrip().endswith("🪙 Токенов: потрачено 11 500 / осталось 4 988 500")


async def test_run_falls_back_to_own_count_when_service_has_no_balance(tmp_path, monkeypatch):
    from radar import pipeline
    _patch(monkeypatch, pipeline, BalanceLLM([None, None]))
    r = await pipeline.run_once(DB(tmp_path / "t.db"), hours=24, source=PostsSource(
        [mk("a", 1, "В Луганске открылся новый филиал ООО Ромашка: вложено 99 млн рублей в запуск производства")]))
    assert r.tokens_approx and r.tokens_spent > 0 and "осталось н/д" in r.digest


async def test_run_stops_when_tokens_are_gone(tmp_path, monkeypatch):
    from radar import pipeline
    _patch(monkeypatch, pipeline, BalanceLLM([0]))
    db = DB(tmp_path / "t.db")
    with pytest.raises(LLMBalanceError):
        await pipeline.run_once(db, hours=24, source=PostsSource([mk("a", 1, "любой текст поста")]))
    assert db.last_run()["status"] == "llm_balance_empty"           # запуск честно записан как «токены закончились»


def test_meta_roundtrip(tmp_path):
    db = DB(tmp_path / "t.db")
    assert db.get_meta("k") is None
    db.set_meta("k", "v")
    assert db.get_meta("k") == "v"


async def test_low_balance_adds_warning_after_tokens_line(tmp_path, monkeypatch):
    from radar import pipeline
    _patch(monkeypatch, pipeline, BalanceLLM([1_000_000, 988_500]))     # ниже порога low_balance_warn
    r = await pipeline.run_once(DB(tmp_path / "t.db"), hours=24, source=PostsSource(
        [mk("a", 1, "В Луганске открылся новый филиал ООО Ромашка: вложено 99 млн рублей в запуск производства")]))
    assert "осталось 988 500" in r.digest and r.digest.rstrip().endswith("пополни баланс у продавца")
