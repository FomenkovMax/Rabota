"""Время для людей: всегда МСК (ЛНР живёт по московскому времени) и с явной пометкой пояса."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from bankintel.formatting import fmt_msk, to_msk


@pytest.mark.parametrize(
    "value,expected",
    [
        (datetime(2026, 10, 27, 12, 15, tzinfo=UTC), "27.10.2026 15:15 МСК"),
        (datetime(2026, 10, 27, 12, 15), "27.10.2026 15:15 МСК"),                      # без пояса = UTC (так отдаёт SQLite)
        ("2026-10-27T12:15:00+00:00", "27.10.2026 15:15 МСК"),                         # ISO-строка набора данных
        (datetime(2026, 10, 27, 18, 15, tzinfo=timezone(timedelta(hours=5))), "27.10.2026 16:15 МСК"),  # чужой пояс пересчитывается
        (datetime(2026, 10, 24, 22, 21, tzinfo=UTC), "25.10.2026 01:21 МСК"),          # переход через полночь меняет и дату
    ],
)
def test_fmt_msk(value, expected):
    assert fmt_msk(value) == expected


def test_date_only_and_missing():
    assert fmt_msk("2026-10-24T22:21:00+00:00", time=False) == "25.10.2026"  # дата тоже по МСК
    assert fmt_msk(None) == "—" and fmt_msk("") == "—"


def test_to_msk_is_fixed_offset_without_dst():
    assert to_msk(datetime(2026, 1, 1, tzinfo=UTC)).utcoffset() == to_msk(datetime(2026, 7, 1, tzinfo=UTC)).utcoffset() == timedelta(hours=3)
