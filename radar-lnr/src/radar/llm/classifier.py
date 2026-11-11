"""Двухступенчатая классификация: дешёвый фильтр (батчами) -> детальный разбор релевантных (JSON + Pydantic)."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from pydantic import ValidationError

from ..dedup import PostGroup
from .client import LLMAuthError, LLMBalanceError, LLMClient, LLMError
from .cost import CostTracker
from .prompts import ANALYZE_SYSTEM, CATEGORY_LIST, FILTER_SYSTEM, SAME_SYSTEM
from .schemas import Event, FilterResult, SameNews
from .verify import sanitize_event

log = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа (учитывает ```json ...``` и лишний текст вокруг)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    return json.loads(text[start:end + 1])


class Classifier:
    def __init__(self, client: LLMClient, env, cfg: dict, banks: list[str], cost: CostTracker, calibration: str = ""):
        self.client, self.cost = client, cost
        self.model_filter, self.model_analyze = env.model_filter, env.model_analyze
        self.batch = cfg["llm"]["filter_batch_size"]
        self.retries = cfg["llm"]["max_retries"]
        self.max_chars = cfg["scrape"]["max_text_chars"]
        cats = CATEGORY_LIST.format(banks=", ".join(banks))
        self.filter_sys = FILTER_SYSTEM.format(cats=cats)
        self.analyze_sys = ANALYZE_SYSTEM.format(cats=cats) + calibration   # примеры по оценкам коллег

    async def _ask_json(self, stage, model, system, user, schema, max_tokens):
        """Запрос с повтором при невалидном JSON (в повторе просим исправиться)."""
        prompt, last_err = user, None
        for attempt in range(self.retries + 1):
            res = await self.client.complete(model, system, prompt, max_tokens)
            self.cost.add(stage, res.tokens_in, res.tokens_out)
            try:
                return schema.model_validate(extract_json(res.text))
            except (ValueError, ValidationError) as e:
                last_err = e
                log.warning("невалидный JSON (%s), попытка %s: %s", stage, attempt + 1, str(e)[:150])
                prompt = user + "\n\nПрошлый ответ был невалидным JSON по схеме. Верни ТОЛЬКО корректный JSON."
        raise LLMError(f"LLM не вернул валидный JSON: {str(last_err)[:150]}")

    async def filter_groups(self, groups: list[PostGroup]) -> list[PostGroup]:
        """Оставляет только релевантные группы. При сбое батча — оставляет всё (лучше лишнее, чем потеря)."""
        keep: list[PostGroup] = []
        for s in range(0, len(groups), self.batch):
            chunk = groups[s:s + self.batch]
            user = "\n\n".join(f"[{i}] {g.main.text[:700]}" for i, g in enumerate(chunk))
            try:
                fr = await self._ask_json("filter", self.model_filter, self.filter_sys, user, FilterResult, 800)
                rel = {r.i for r in fr.results if r.relevant}
                keep += [g for i, g in enumerate(chunk) if i in rel]
            except (LLMAuthError, LLMBalanceError):
                raise
            except LLMError as e:
                log.error("фильтр не сработал для батча, оставляем все посты: %s", e)
                keep += chunk
        return keep

    async def analyze_group(self, g: PostGroup) -> dict | None:
        text = g.main.text[:self.max_chars]
        ev = await self._ask_json("analyze", self.model_analyze, self.analyze_sys, f"Новость:\n{text}", Event, 1200)
        ev = sanitize_event(ev, "\n".join(p.text for p in g.posts))  # проверяем по ВСЕМ текстам группы
        d = ev.model_dump()
        d["source_urls"] = g.urls          # ссылки подставляем сами — LLM их не придумает
        d["channels"] = sorted({p.channel for p in g.posts})
        d["post_keys"] = [f"{p.channel}/{p.post_id}" for p in g.posts]   # чтобы повторы узнавались в следующих запусках
        d["image_url"] = next((p.image_url for p in sorted(g.posts, key=lambda p: p is not g.main) if p.image_url), None)
        d["published_at"] = g.main.published_at.isoformat()
        return d

    async def same_news(self, a: dict, b: dict) -> bool:
        """Спорная пара событий: одна ли это новость? Ошибка LLM = «нет» (лучше повтор, чем потеря новости)."""
        user = (f"Новость А: {a.get('title')}. {a.get('summary')}\n\n"
                f"Новость Б: {b.get('title')}. {b.get('summary')}")
        try:
            return (await self._ask_json("filter", self.model_filter, SAME_SYSTEM, user, SameNews, 60)).same
        except LLMAuthError:
            raise
        except LLMError as e:      # в т.ч. «токены закончились»: разбор уже сделан, запуск доводим до конца
            log.warning("проверка дубля не удалась: %s", e)
            return False

    async def analyze_all(self, groups: list[PostGroup], concurrency: int = 3) -> list[dict]:
        sem = asyncio.Semaphore(concurrency)

        async def one(g):
            async with sem:
                try:
                    return await self.analyze_group(g)
                except (LLMAuthError, LLMBalanceError):
                    raise
                except LLMError as e:
                    log.error("разбор не удался (%s): %s", g.main.url, e)
                    return None

        return [e for e in await asyncio.gather(*(one(g) for g in groups)) if e]
