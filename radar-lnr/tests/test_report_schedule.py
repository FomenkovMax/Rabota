import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from radar.bot.auth import GROUP_COMMANDS, WhitelistMiddleware
from radar.bot.sender import is_quiet
from radar.config import get_settings
from radar.db import DB
from radar.report.snapshot import build_report

CFG = get_settings()


def ev(i, score, title=None, cat=1):
    return {"category": cat, "title": title or f"Событие номер {i}", "summary": "Суть события " * 5, "relevance_score": score,
            "organizations": [{"name": f"ООО Компания {i}", "inn_if_in_text": None}], "persons": [], "amounts": [],
            "source_urls": [f"https://t.me/ch/{i}"], "channels": ["ch"], "post_keys": [f"ch/{i}"]}


# ------------------------------------------------------------------ /report из сохранённого
def test_report_rebuilds_from_db_without_llm_and_includes_files(tmp_path):
    db = DB(tmp_path / "t.db")
    for i, sc in enumerate([5, 4, 3, 2, 1]):
        db.save_event(1, ev(i, sc))
    text, files, n = asyncio.run(build_report(db, 24, CFG, tmp_path / "out", tokens_left=19_395_118))
    assert n == 5
    assert "Отчёт за последние 24 ч" in text and "Событий от 3⭐: 3" in text      # в сообщении только от 3⭐
    assert "⭐2" not in text and "⭐1" not in text
    assert text.rstrip().endswith("🪙 Токенов осталось: 19 395 118") and len(text) < 4096
    names = sorted(f.suffix for f in files)
    assert names == [".html", ".pdf", ".xlsx"]                                     # PDF + дашборд + Excel (от 2⭐)


def test_report_with_no_events_still_answers(tmp_path):
    text, files, n = asyncio.run(build_report(DB(tmp_path / "t.db"), 24, CFG, tmp_path / "out"))
    assert n == 0 and files == [] and "Новых значимых событий нет" in text


# ------------------------------------------------------------------ кто может писать команды
def _msg(user_id, chat_id, text):
    answers = []

    async def answer(t, **k): answers.append(t)
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id, username="u"), chat=SimpleNamespace(id=chat_id),
                           text=text, answer=answer), answers


def _run(mw, msg):
    called = []

    async def handler(m, d): called.append(1)
    asyncio.run(mw(handler, msg, {}))
    return bool(called)


def test_group_members_can_use_report_but_not_digest():
    mw = WhitelistMiddleware(allowed={1}, group_ids={-100})
    assert "/report" in GROUP_COMMANDS and "/digest" not in GROUP_COMMANDS and "/inn" not in GROUP_COMMANDS
    m, _ = _msg(999, -100, "/report@Radar_Bank_Bot 24")            # посторонний id, но в группе дайджеста
    assert _run(mw, m)
    m, ans = _msg(999, -100, "/digest")                             # тратит токены — только админ/whitelist
    assert not _run(mw, m) and ans
    m, _ = _msg(999, -555, "/report")                               # чужая группа / личка — нельзя
    assert not _run(mw, m)
    m, _ = _msg(1, 1, "/digest")                                    # whitelist — как раньше
    assert _run(mw, m)


# ------------------------------------------------------------------ расписание и тихие часы
def test_schedule_runs_every_4_hours_on_the_clock_moscow():
    hours = CFG["digest"]["schedule_hours"]
    assert hours == [0, 4, 8, 12, 16, 20]
    tz = ZoneInfo("Europe/Moscow")
    trig = CronTrigger(hour=",".join(map(str, hours)), minute=0, timezone=tz)
    t = datetime(2026, 10, 14, 15, 59, tzinfo=tz)
    seq = []
    for _ in range(3):
        t = trig.get_next_fire_time(None, t)
        seq.append(t.strftime("%H:%M"))
        t = t.replace(minute=1)
    assert seq == ["16:00", "20:00", "00:00"]


def test_quiet_hours_wrap_over_midnight():
    q = CFG["digest"]["quiet_hours"]
    assert q == [23, 7]
    assert [is_quiet(h, q) for h in (22, 23, 0, 6, 7, 12)] == [False, True, True, True, False, False]
    assert not is_quiet(3, None) and not is_quiet(3, [])
