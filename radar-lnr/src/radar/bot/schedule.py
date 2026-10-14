"""Расписание плановых дайджестов: без звука в выбранные слоты и «наверстывание» пропущенного слота."""
from __future__ import annotations

from datetime import datetime, timedelta


def is_silent_slot(hour: int, silent_hours: list[int] | None) -> bool:
    """Плановый дайджест этого часа (по МСК) приходит без звука уведомления? Напр. silent_hours=[0, 4]."""
    return bool(silent_hours) and hour in silent_hours


def max_gap_hours(schedule_hours: list[int] | None, every_hours: float = 4) -> float:
    """Самый длинный перерыв между плановыми слотами (с учётом перехода через полночь)."""
    hrs = sorted(set(schedule_hours or []))
    if len(hrs) < 2:
        return 24.0 if hrs else float(every_hours)
    return float(max((b - a) for a, b in zip(hrs, hrs[1:] + [hrs[0] + 24])))


def needs_catchup(last_success: datetime | None, now: datetime, schedule_hours: list[int] | None,
                  every_hours: float = 4, slack_hours: float = 0.5) -> bool:
    """Если после перезапуска/простоя слот был пропущен (с последнего успешного запуска прошло больше самого
    длинного перерыва + запас) — нужно один раз наверстать сразу, не дожидаясь следующего слота."""
    if last_success is None:
        return True
    return now - last_success > timedelta(hours=max_gap_hours(schedule_hours, every_hours) + slack_hours)
