"""Оркестратор обогащения: адаптеры, кэш SQLite (TTL 7 дней), правило «не угадывать»."""
from __future__ import annotations

import logging

from rapidfuzz import fuzz

from ..db import DB
from ..dedup import clean_org_name as _clean_name
from ..llm.verify import inn_checksum_ok
from .base import Adapter, AdapterError, LookupResult, OrgCard

log = logging.getLogger(__name__)
NAME_MATCH = 90   # порог похожести названия для автоматического принятия
NAME_GAP = 15     # и отрыв от второго кандидата (если их несколько), иначе — «требует проверки»
def name_score(query: str, card: OrgCard) -> float:
    """Похожесть названия из новости и названия в реестре, 0..100.
    Сравниваем целиком (ratio / token_sort), а НЕ token_set: тот даёт 100, когда одно название — подмножество
    другого («ПГ Родина» ⊂ «Промышленная группа Родина»), и это приводило к ложным совпадениям."""
    a, b = _clean_name(query), _clean_name(card.name_short or card.name_full or "")
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))


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
        """Поиск по названию.
        1) Ищем в ЛНР. Один явный победитель по названию -> found; иначе -> «требует проверки» + топ-3.
        2) Если в ЛНР пусто — ищем по России и показываем варианты ТОЛЬКО как подсказку (needs_review),
           автоматически такие совпадения не принимаются."""
        key = f"name:v3:{_clean_name(name)}"   # v3: ранжирование по полному совпадению + подсказки вне ЛНР
        if (cached := self.db.cache_get(key, self.ttl)):
            return LookupResult.from_dict(cached)
        if not self.adapters:
            return LookupResult("disabled", message="Обогащение выключено (нет ключа DaData)")

        async def search(anywhere: bool) -> list[OrgCard]:
            for ad in self.adapters:
                found = await ad.by_name(name, self.region, anywhere=anywhere)
                if found:
                    return found
            return []

        try:
            lnr = await search(False)
            wide = [] if lnr else await search(True)
        except AdapterError as e:
            return LookupResult("error", message=str(e))   # ошибки не кэшируем

        if lnr:
            ranked = sorted(lnr, key=lambda c: name_score(name, c), reverse=True)
            top = name_score(name, ranked[0])
            gap_ok = len(ranked) == 1 or top - name_score(name, ranked[1]) >= NAME_GAP
            if top >= NAME_MATCH and gap_ok:
                res = LookupResult("found", card=ranked[0])
            else:
                res = LookupResult("needs_review", candidates=ranked[:3],
                                   message="Требует проверки: несколько вариантов в ЛНР")
        elif wide:
            ranked = sorted(wide, key=lambda c: name_score(name, c), reverse=True)
            res = LookupResult("needs_review", candidates=ranked[:3],
                               message="В ЛНР не найдено. Варианты вне ЛНР — только подсказка, проверь вручную")
        else:
            res = LookupResult("not_found", message="Не найдено")
        self.db.cache_put(key, res.to_dict())
        return res

    async def enrich_event(self, ev: dict) -> None:
        """Дописывает ev['enriched'] — лучший результат среди первых 3 организаций новости:
        сначала любая «found», иначе первая «needs_review». Поле matched_org — какая именно организация."""
        orgs = (ev.get("organizations") or [])[:3]
        if not orgs or not self.adapters:
            return
        best = None
        for org in orgs:
            res = (await self.lookup_inn(org["inn_if_in_text"]) if org.get("inn_if_in_text")
                   else await self.lookup_name(org["name"], org.get("region")))
            if res.status == "found":
                best = (org, res)
                break
            if res.status == "needs_review" and best is None:
                best = (org, res)
        if best:
            org, res = best
            ev["enriched"] = {**res.to_dict(), "matched_org": org["name"]}


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
