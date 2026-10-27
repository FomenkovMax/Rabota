"""Один запуск: сбор -> дедуп -> фильтр -> разбор -> сохранение -> дайджест."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import get_env, get_settings, load_channels, load_yaml
from .db import DB
from .dedup import group_similar, match_history_posts, merge_event_into
from .event_dedup import dedup_events
from .finance import effect_text, estimate
from .report.export import export_files
from .report.pdf import make_onepager
from .enrichment.service import Enricher, build_adapters
from .llm.classifier import Classifier
from .llm.client import LLMAuthError, LLMBalanceError, make_client
from .llm.cost import CostTracker
from .report.feedback import calibration_text
from .report.digest import build_digest, usage_line
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
    files: list = field(default_factory=list)   # PDF, HTML-дашборд и Excel для вложения
    tokens_before: int | None = None             # остаток токенов у LLM-сервиса до запуска
    tokens_left: int | None = None               # ...и после запуска
    tokens_spent: int | None = None
    tokens_approx: bool = False                  # True — «потрачено» оценено самим ботом (сервис баланс не отдаёт)


async def run_once(db: DB, hours: float | None = None, dry_run: bool = False, limit_channels: int | None = None,
                   source: TmeWebSource | None = None, build_outputs: bool = True) -> RunResult:
    """Выполняет полный цикл. hours — принудительное окно (для демо); иначе «с прошлого успешного запуска».
    dry_run=True: ничего не сохраняем в БД (посты не помечаются прочитанными).
    build_outputs=False: фоновый сбор — только база, без дайджеста/PDF/Excel (их соберёт ежедневная рассылка)."""
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
        client = make_client(env)
        # ---- 0. баланс токенов: если закончились — не начинаем, понятно сообщаем ----
        res.tokens_before = await client.get_balance()
        if res.tokens_before is not None:
            log.info("Баланс токенов до запуска: %s", res.tokens_before)
            if res.tokens_before <= cfg["llm"].get("min_balance_to_run", 0):
                raise LLMBalanceError(f"токены закончились: осталось {res.tokens_before}")
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

        # ---- 2. дедуп по тексту: внутри запуска и с постами прошлых дней ----
        dcfg = cfg["dedup"]
        groups = group_similar(all_posts, dcfg["similarity_threshold"])
        log.info("Групп (инфоповодов) после дедупа внутри запуска: %d", len(groups))
        history_posts = db.recent_posts(dcfg["history_days"])
        groups, attach, skipped_old = match_history_posts(groups, history_posts, dcfg["similarity_threshold"])
        log.info("Повторов прошлых постов: к событиям %d, нерелевантных пропущено %d; новых групп: %d",
                 sum(len(v) for v in attach.values()), skipped_old, len(groups))
        if attach and not dry_run:   # новый источник к уже показанному событию, без повторного показа
            for eid, gs in attach.items():
                if (old := db.get_event(eid)):
                    for g in gs:
                        merge_event_into(old, {"source_urls": g.urls, "channels": sorted({p.channel for p in g.posts}),
                                               "post_keys": [f"{p.channel}/{p.post_id}" for p in g.posts]})
                    db.update_event(eid, old)
                    db.link_posts(eid, old["post_keys"])

        # ---- 3. LLM ----
        if groups:
            clf = Classifier(client, env, cfg, load_yaml("config/competitors.yaml")["banks"], res.cost,
                             calibration_text(db.feedback_rows()))
            relevant = await clf.filter_groups(groups)
            log.info("Релевантных после фильтра: %d из %d", len(relevant), len(groups))
            res.events = await clf.analyze_all(relevant)
            # ---- склейка по смыслу: пересказы и повторы через несколько часов/дней ----
            res.events, n_in, n_old = await dedup_events(
                res.events, db.recent_events(dcfg["history_days"]), clf, None if dry_run else db,
                dcfg.get("llm_max_calls", 15))
            log.info("Дубли по смыслу: склеено внутри запуска %d, привязано к прошлым событиям %d; новых: %d",
                     n_in, n_old, len(res.events))
            # обогащение организаций (DaData и др.); сбой обогащения не ломает запуск
            enricher = Enricher(db, build_adapters(env, cfg), cfg["enrichment"]["cache_ttl_days"])
            for ev in res.events:
                try:
                    await enricher.enrich_event(ev)
                except Exception as e:
                    log.warning("обогащение не удалось для %r: %s", ev.get("title"), e)
            for ev in res.events:   # оценка фин. эффекта (после обогащения: нужна численность/ОКВЭД)
                ev["finance"] = estimate(ev)
                ev["fin_effect_text"] = effect_text(ev["finance"])

        # ---- 4. сохранение и дайджест ----
        if not dry_run:
            db.save_posts(all_posts, run_id)
            for ev in res.events:
                ev["id"] = db.save_event(run_id, ev)
                db.link_posts(ev["id"], ev.get("post_keys") or [])
        # ---- остаток и расход токенов: по данным сервиса (разница баланса); нет баланса — оценка бота ----
        res.tokens_left = await client.get_balance()
        if res.tokens_before is not None and res.tokens_left is not None:
            res.tokens_spent = max(0, res.tokens_before - res.tokens_left)
        else:
            res.tokens_spent, res.tokens_approx = res.cost.tokens_in + res.cost.tokens_out, True
        warn = cfg["llm"].get("low_balance_warn")
        tokens_line = usage_line(res.tokens_spent, res.tokens_left, res.tokens_approx, warn)
        d = cfg["digest"]
        if not build_outputs:
            log.info(res.cost.summary())
            if not dry_run:
                db.finish_run(run_id, "ok", posts_new=res.posts_new, events_n=len(res.events),
                              tokens_in=res.cost.tokens_in, tokens_out=res.cost.tokens_out,
                              cost_usd=res.cost.cost_usd, channel_errors=res.channel_errors,
                              tokens_spent=None if res.tokens_approx else res.tokens_spent, tokens_left=res.tokens_left)
            return res
        res.digest = build_digest(res.events, since, until, len(res.channel_errors), d["timezone"],
                                  d["max_events"], d["min_score"], d.get("dashboard_min_score", 2), tokens_line)
        dash_events = [e for e in res.events if e["relevance_score"] >= d.get("dashboard_min_score", 2)]
        exports = get_env().data_path / "exports"
        if dash_events:   # в дашборд и Excel — события от 2 звёзд
            res.files = export_files(dash_events, since, until, exports)
        try:              # одностраничный PDF с главными новостями (от 3 звёзд) — первым файлом; сбой не критичен
            if (pdf := await make_onepager(res.events, since, until, exports, d["min_score"], d["timezone"])):
                res.files.insert(0, pdf)
        except Exception as e:
            log.warning("PDF «Главное» не создан: %s: %s", type(e).__name__, e)
        log.info(res.cost.summary())
        if not dry_run:
            db.finish_run(run_id, "ok", posts_new=res.posts_new, events_n=len(res.events),
                          tokens_in=res.cost.tokens_in, tokens_out=res.cost.tokens_out,
                          cost_usd=res.cost.cost_usd, channel_errors=res.channel_errors,
                          tokens_spent=None if res.tokens_approx else res.tokens_spent, tokens_left=res.tokens_left)
        return res
    except LLMBalanceError:
        if not dry_run:
            db.finish_run(run_id, "llm_balance_empty", channel_errors=res.channel_errors)
        raise
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
