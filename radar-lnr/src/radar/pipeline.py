"""Один запуск: сбор -> дедуп -> фильтр -> разбор -> сохранение -> дайджест."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import get_env, get_settings, load_channels, load_yaml
from .db import DB
from .dedup import group_similar
from .llm.classifier import Classifier
from .llm.client import LLMAuthError, make_client
from .llm.cost import CostTracker
from .report.digest import build_digest
from .sources.tme_web import ChannelUnavailable, TmeWebSource

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: int
    since: datetime
    until: datetime
    events: list[dict] = field(default_factory=list)
    channel_errors: dict[str, str] = field(default_factory=dict)
    posts_new: int = 0
    cost: CostTracker | None = None
    digest: str = ""


async def run_once(db: DB, hours: float | None = None, dry_run: bool = False, limit_channels: int | None = None,
                   source: TmeWebSource | None = None) -> RunResult:
    """Выполняет полный цикл. hours — принудительное окно (для демо); иначе «с прошлого успешного запуска».
    dry_run=True: ничего не сохраняем в БД (посты не помечаются прочитанными)."""
    env, cfg = get_env(), get_settings()
    until = datetime.now(timezone.utc)
    last = db.last_success()
    if hours is not None:
        since = until - timedelta(hours=hours)
    else:
        since = last or until - timedelta(hours=cfg["scrape"]["first_run_hours"])

    run_id = 0 if dry_run else db.start_run()
    res = RunResult(run_id, since, until)
    res.cost = CostTracker(cfg["llm"]["prices"])
    own_source = source is None
    source = source or TmeWebSource(cfg["scrape"])
    try:
        # ---- 1. сбор ----
        channels = load_channels()[:limit_channels]
        all_posts = []
        for ch in channels:
            name = ch["username"]
            try:
                posts = await source.fetch(name, since)
                known = db.known_posts(name, [p.post_id for p in posts]) if not dry_run else set()
                posts = [p for p in posts if p.post_id not in known]  # дедуп по (channel, post_id)
                all_posts += posts
            except ChannelUnavailable as e:
                res.channel_errors[name] = str(e)
                log.warning("канал %s: %s", name, e)
            except Exception as e:  # один канал не должен ронять запуск
                res.channel_errors[name] = f"неожиданная ошибка: {e!r}"
                log.exception("канал %s упал", name)
            await source.polite_pause()
        res.posts_new = len(all_posts)
        log.info("Собрано новых постов: %d, ошибок каналов: %d", len(all_posts), len(res.channel_errors))

        # ---- 2. дедуп по тексту ----
        groups = group_similar(all_posts, cfg["dedup"]["similarity_threshold"])
        log.info("Групп (инфоповодов) после дедупа: %d", len(groups))

        # ---- 3. LLM ----
        if groups:
            clf = Classifier(make_client(env), env, cfg, load_yaml("config/competitors.yaml")["banks"], res.cost)
            relevant = await clf.filter_groups(groups)
            log.info("Релевантных после фильтра: %d из %d", len(relevant), len(groups))
            res.events = await clf.analyze_all(relevant)

        # ---- 4. сохранение и дайджест ----
        if not dry_run:
            db.save_posts(all_posts, run_id)
            for ev in res.events:
                ev["id"] = db.save_event(run_id, ev)
        d = cfg["digest"]
        res.digest = build_digest(res.events, since, until, len(res.channel_errors), d["timezone"],
                                  d["max_events"], d["min_score"])
        log.info(res.cost.summary())
        if not dry_run:
            db.finish_run(run_id, "ok", posts_new=res.posts_new, events_n=len(res.events),
                          tokens_in=res.cost.tokens_in, tokens_out=res.cost.tokens_out,
                          cost_usd=res.cost.cost_usd, channel_errors=res.channel_errors)
        return res
    except LLMAuthError:
        if not dry_run:
            db.finish_run(run_id, "llm_auth_error", channel_errors=res.channel_errors)
        raise
    except Exception:
        if not dry_run:
            db.finish_run(run_id, "error", channel_errors=res.channel_errors)
        raise
    finally:
        if own_source:
            await source.aclose()
