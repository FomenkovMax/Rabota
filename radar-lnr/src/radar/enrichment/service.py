"""Оркестратор обогащения: адаптеры, кэш SQLite (TTL 7 дней), правило «не угадывать»."""
from __future__ import annotations

import logging

from rapidfuzz import fuzz

from ..db import DB
from ..dedup import normalize
from ..llm.verify import inn_checksum_ok
from .base import Adapter, AdapterError, LookupResult, OrgCard

log = logging.getLogger(__name__)
NAME_MATCH = 90   # порог похожести названия, при котором единственный кандидат считается найденным
OPF = r"\b(ооо|оао|зао|пао|ао|гуп|муп|гбу|гбуз|фгуп|фгбу|нко|ип)\b"


def _clean_name(s: str) -> str:
    import re
    return re.sub(OPF, " ", normalize(s)).strip()


class Enricher:
    def __init__(self, db: DB, adapters: list[Adapter], cache_ttl_days: int = 7, region: str = "Луганская"):
        self.db, self.adapters, self.ttl, self.region = db, adapters, cache_ttl_days, region

    async def lookup_inn(self, inn: str) -> LookupResult:
        inn = "".join(ch for ch in inn if ch.isdigit())
        if not inn_checksum_ok(inn):
            return LookupResult("error", message="ИНН не прошёл проверку (неверная длина или контрольная сумма)")
        key = f"inn:{inn}"
        if (cached := self.db.cache_get(key, self.ttl)):
            return LookupResult.from_dict(cached)
        if not self.adapters:
            return LookupResult("disabled", message="Обогащение выключено (нет ключа DaData)")
        found: list[OrgCard] = []
        for ad in self.adapters:
            try:
                found = await ad.by_inn(inn)
            except AdapterError as e:
                return LookupResult("error", message=str(e))   # ошибки не кэшируем
            if found:
                break
        if not found:
            res = LookupResult("not_found", message="Организация с таким ИНН не найдена")
        else:
            res = LookupResult("found", card=found[0])
        self.db.cache_put(key, res.to_dict())
        return res

    async def lookup_name(self, name: str, region: str | None = None) -> LookupResult:
        """Поиск по названию. Единственный и очень похожий кандидат — найден; иначе «требует проверки» + топ-3."""
        key = f"name:v2-lnr:{_clean_name(name)}"   # v2: поиск только в ЛНР (по kladr_id)
        if (cached := self.db.cache_get(key, self.ttl)):
            return LookupResult.from_dict(cached)
        if not self.adapters:
            return LookupResult("disabled", message="Обогащение выключено (нет ключа DaData)")
        cands: list[OrgCard] = []
        for ad in self.adapters:
            try:
                cands = await ad.by_name(name, self.region)
            except AdapterError as e:
                return LookupResult("error", message=str(e))
            if cands:
                break
        if not cands:
            res = LookupResult("not_found", message="Не найдено в ЛНР")
        else:
            q = _clean_name(name)
            score = lambda c: fuzz.token_set_ratio(q, _clean_name(c.name_short or c.name_full or ""))  # noqa: E731
            ranked = sorted(cands, key=score, reverse=True)
            # единственный кандидат с высокой похожестью — не гадаем, если их несколько
            if len(ranked) == 1 and score(ranked[0]) >= NAME_MATCH:
                res = LookupResult("found", card=ranked[0])
            else:
                res = LookupResult("needs_review", candidates=ranked[:3], message="Требует проверки: несколько вариантов")
        self.db.cache_put(key, res.to_dict())
        return res

    async def enrich_event(self, ev: dict) -> None:
        """Дописывает ev['enriched'] для главной организации события (если она есть)."""
        orgs = ev.get("organizations") or []
        if not orgs or not self.adapters:
            return
        org = orgs[0]
        res = (await self.lookup_inn(org["inn_if_in_text"]) if org.get("inn_if_in_text")
               else await self.lookup_name(org["name"], org.get("region")))
        if res.status in ("found", "needs_review"):
            ev["enriched"] = res.to_dict()


def build_adapters(env, cfg: dict) -> list[Adapter]:
    ad: list[Adapter] = []
    ecfg = cfg.get("enrichment", {})
    key = env.dadata_api_key.get_secret_value()
    if ecfg.get("dadata", {}).get("enabled") and key:
        from .dadata import DaDataAdapter
        ad.append(DaDataAdapter(key))
    elif ecfg.get("dadata", {}).get("enabled"):
        log.warning("DaData включена в settings.yaml, но DADATA_API_KEY пуст — обогащение пропущено")
    for name in ("companium", "busgov"):
        if ecfg.get(name, {}).get("enabled"):
            log.warning("Адаптер %s пока не реализован (нужна проверка robots.txt и разметки) — пропущен", name)
    return ad
