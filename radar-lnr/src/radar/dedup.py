"""Дедупликация: один инфоповод из нескольких каналов = одно событие со списком источников."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

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
