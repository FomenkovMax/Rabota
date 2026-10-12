from datetime import datetime, timezone

from radar.dedup import group_similar
from radar.sources.base import Post


def mk(ch, pid, text):
    return Post(ch, pid, f"https://t.me/{ch}/{pid}", text, datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_same_news_from_three_channels_is_one_group():
    base = "В Луганске открылся новый филиал сети магазинов «Продукты», в нём будут работать 120 сотрудников"
    posts = [mk("a", 1, base), mk("b", 7, "🔥 " + base + "!"), mk("c", 3, base.lower() + " https://x.ru")]
    groups = group_similar(posts)
    assert len(groups) == 1 and len(groups[0].urls) == 3


def test_different_news_stay_separate():
    posts = [mk("a", 1, "В Луганске открылся новый филиал сети магазинов, будут работать 120 сотрудников"),
             mk("b", 2, "Правительство утвердило программу развития дорожной сети на ближайшие три года")]
    assert len(group_similar(posts)) == 2


def test_duplicate_channel_post_id_ignored():
    p = mk("a", 1, "Текст новости про организацию и её руководителя, достаточно длинный для сравнения")
    assert len(group_similar([p, p])) == 1 and len(group_similar([p, p])[0].posts) == 1


def test_short_texts_not_merged_by_fuzz():
    assert len(group_similar([mk("a", 1, "Открылся магазин"), mk("b", 2, "Открылся банк")])) == 2
