"""Дедупликация: один инфоповод из нескольких каналов = одно событие со списком источников."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .sources.base import Post


def normalize(text: str) -> str:
    """Нижний регистр, без ссылок/эмодзи/знаков препинания, ё->е."""
    t = text.lower().replace("ё", "е")
    t = re.sub(r"https?://\S+|@\w+|#\w+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class PostGroup:
    """Группа похожих постов. Первый — «главный» (самый длинный текст)."""
    posts: list[Post] = field(default_factory=list)

    @property
    def main(self) -> Post:
        return max(self.posts, key=lambda p: len(p.text))

    @property
    def urls(self) -> list[str]:
        return [p.url for p in self.posts]


def group_similar(posts: list[Post], threshold: int = 88) -> list[PostGroup]:
    """Жадная кластеризация: пост присоединяется к первой группе, на которую похож."""
    groups: list[tuple[str, PostGroup]] = []  # (нормализованный текст главного, группа)
    seen: set[tuple[str, int]] = set()
    for p in posts:
        key = (p.channel, p.post_id)
        if key in seen:  # дубль (channel, post_id) внутри одного запуска
            continue
        seen.add(key)
        norm = normalize(p.text)
        for gnorm, g in groups:
            # короткие тексты сравниваем только на полное совпадение — иначе ложные склейки
            if min(len(norm), len(gnorm)) < 40:
                same = norm == gnorm
            else:
                same = fuzz.token_set_ratio(norm, gnorm) >= threshold
            if same:
                g.posts.append(p)
                break
        else:
            groups.append((norm, PostGroup([p])))
    return [g for _, g in groups]


# ======================================================================================
# Дедупликация ПО ИСТОРИИ (между запусками) и ПО СМЫСЛУ (пересказ другими словами)
# ======================================================================================
OPF = r"\b(ооо|оао|зао|пао|ао|гуп|муп|гбу|гбуз|фгуп|фгбу|нко|ип)\b"


def clean_org_name(s: str) -> str:
    """Название организации без «ООО/ГУП/…», кавычек и регистра — для сравнения."""
    return re.sub(OPF, " ", normalize(s)).strip()


def _long_enough_or_equal(a: str, b: str, threshold: int) -> bool:
    if min(len(a), len(b)) < 40:      # короткие тексты — только полное совпадение, иначе ложные склейки
        return a == b
    return fuzz.token_set_ratio(a, b) >= threshold


def match_history_posts(groups: list[PostGroup], history: list[dict], threshold: int = 88):
    """Сверяет новые группы постов с постами за последние дни.
    Возвращает (новые_группы, {event_id: [группы-повторы]}, сколько_повторов_нерелевантных_постов).
    Повтор релевантного поста -> источник добавится к прошлому событию; повтор нерелевантного -> пропуск."""
    hist = [(normalize(h["text"] or ""), h) for h in history]
    hist = [(n, h) for n, h in hist if n]
    norms = [n for n, _ in hist]
    fresh: list[PostGroup] = []
    attach: dict[int, list[PostGroup]] = {}
    skipped = 0
    for g in groups:
        n = normalize(g.main.text)
        hit = None
        if norms:
            if len(n) >= 40:
                m = process.extractOne(n, norms, scorer=fuzz.token_set_ratio, score_cutoff=threshold)
                if m and min(len(n), len(norms[m[2]])) >= 40:
                    hit = hist[m[2]][1]
            else:
                hit = next((h for hn, h in hist if hn == n), None)
        if hit is None:
            fresh.append(g)
        elif hit.get("event_id"):
            attach.setdefault(hit["event_id"], []).append(g)
        else:
            skipped += 1
    return fresh, attach, skipped


def _org_keys(ev: dict) -> set[str]:
    keys: set[str] = set()
    for o in ev.get("organizations") or []:
        if o.get("name"):
            keys.add("n:" + clean_org_name(o["name"]))
        if o.get("inn_if_in_text"):
            keys.add("i:" + o["inn_if_in_text"])
    card = (ev.get("enriched") or {}).get("card") or {}
    if card.get("inn"):
        keys.add("i:" + card["inn"])
    keys.discard("n:")
    return keys


def _orgs_overlap(a: dict, b: dict) -> bool:
    ka, kb = _org_keys(a), _org_keys(b)
    if ka & kb:
        return True
    names_a = [k[2:] for k in ka if k.startswith("n:")]
    names_b = [k[2:] for k in kb if k.startswith("n:")]
    return any(fuzz.ratio(x, y) >= 90 for x in names_a for y in names_b)


def _facts(ev: dict) -> set[str]:
    """Значимые числа новости. Суммы и численность берём любые ('99', '11.4'), числа из текста — только
    длинные/дробные ('2030', '11.4'), чтобы «22 октября» не считалось общим фактом."""
    from .llm.verify import numbers_in
    facts = numbers_in(" ".join(ev.get("amounts") or []))
    if ev.get("employees_mentioned"):
        facts.add(str(ev["employees_mentioned"]))
    facts |= {n for n in numbers_in(" ".join([ev.get("title", ""), ev.get("summary", "")])) if len(n) >= 3 or "." in n}
    return facts


def _content_title(ev: dict) -> str:
    """Заголовок без слов из названий организаций: «Ромашка начала поставки» -> «начала поставки».
    Иначе два разных события об одной компании выглядят «похожими» только из-за её названия."""
    org_words = {w for o in ev.get("organizations") or [] for w in clean_org_name(o.get("name", "")).split()}
    words = [w for w in normalize(ev.get("title", "")).split() if w not in org_words]
    return " ".join(words) if sum(len(w) >= 4 for w in words) >= 2 else ""


def same_event(a: dict, b: dict) -> str:
    """'yes' — одна и та же новость, 'maybe' — похоже (нужна проверка LLM), 'no' — разные.
    Правило: одна организация И общий факт/похожая суть заголовка. Разные факты об одной организации не склеиваем."""
    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    sa, sb = normalize(a.get("summary", "")), normalize(b.get("summary", ""))
    raw_title = fuzz.token_set_ratio(ta, tb) if min(len(ta), len(tb)) >= 15 else 0
    ca, cb = _content_title(a), _content_title(b)
    title_sim = fuzz.token_set_ratio(ca, cb) if ca and cb else 0       # суть заголовка без названия организации
    sum_sim = fuzz.token_set_ratio(sa, sb) if min(len(sa), len(sb)) >= 40 else 0
    common = _facts(a) & _facts(b)
    orgs = _orgs_overlap(a, b)
    if raw_title >= 95 and (title_sim >= 60 or not (ca and cb)):       # практически одинаковые заголовки
        return "yes"
    if orgs and (common or title_sim >= 75 or sum_sim >= 80):
        return "yes"
    if orgs and (title_sim >= 45 or sum_sim >= 55):
        return "maybe"
    if not _org_keys(a) and not _org_keys(b) and raw_title >= 80:
        return "maybe"
    return "no"


def merge_event_into(base: dict, extra: dict) -> None:
    """Добавляет к событию `base` источники/каналы/посты из `extra`; оценка — максимальная."""
    for key in ("source_urls", "channels", "post_keys"):
        merged = list(dict.fromkeys([*(base.get(key) or []), *(extra.get(key) or [])]))
        base[key] = merged
    base["relevance_score"] = max(base.get("relevance_score", 1), extra.get("relevance_score", 1))
    if not base.get("image_url") and extra.get("image_url"):
        base["image_url"] = extra["image_url"]
