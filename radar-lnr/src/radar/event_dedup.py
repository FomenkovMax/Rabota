"""Склейка событий по смыслу: внутри запуска и с событиями прошлых дней.

Зачем: один инфоповод разные каналы публикуют в разное время и разными словами. Без этого бот выдавал бы
одну и ту же новость как новую в каждом следующем дайджесте.
"""
from __future__ import annotations

import logging

from .db import DB
from .dedup import merge_event_into, same_event

log = logging.getLogger(__name__)


async def _is_dup(new: dict, other: dict, clf, budget: list[int]) -> bool:
    verdict = same_event(new, other)
    if verdict == "yes":
        return True
    if verdict == "maybe" and clf is not None and budget[0] > 0:
        budget[0] -= 1
        return await clf.same_news(new, other)
    return False


async def dedup_events(new_events: list[dict], history: list[dict], clf, db: DB | None,
                       max_llm_calls: int = 15) -> tuple[list[dict], int, int]:
    """Возвращает (уникальные_новые, склеено_внутри_запуска, привязано_к_прошлым).
    1) внутри запуска: сильные события первыми, остальные склеиваются с ними;
    2) с историей: если событие уже было — добавляем источник к старому и НЕ показываем как новое."""
    budget = [max_llm_calls]
    kept: list[dict] = []
    merged_inside = 0
    for ev in sorted(new_events, key=lambda e: -e["relevance_score"]):
        for k in kept:
            if await _is_dup(ev, k, clf, budget):
                merge_event_into(k, ev)
                merged_inside += 1
                break
        else:
            kept.append(ev)

    fresh: list[dict] = []
    attached = 0
    for ev in kept:
        for old in history:
            if await _is_dup(ev, old, clf, budget):
                merge_event_into(old, ev)       # у старого события появился ещё один источник
                if db is not None:
                    db.update_event(old["id"], old)
                    db.link_posts(old["id"], ev.get("post_keys") or [])
                attached += 1
                log.info("повтор прошлого события #%s: %r", old["id"], ev.get("title"))
                break
        else:
            fresh.append(ev)
    if budget[0] < max_llm_calls:
        log.info("проверок дублей через LLM: %d", max_llm_calls - budget[0])
    return fresh, merged_inside, attached
