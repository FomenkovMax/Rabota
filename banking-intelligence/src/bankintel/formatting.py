"""Единое форматирование чисел для бота и отчётов."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

# ЛНР живёт по московскому времени: UTC+3, перехода на летнее время нет.
MSK = timezone(timedelta(hours=3), "МСК")


def to_msk(value: datetime | str) -> datetime:
    """Момент времени в МСК. В БД время хранится в UTC; SQLite отдаёт его без пояса — считаем его UTC."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MSK)


def fmt_msk(value: datetime | str | None, *, time: bool = True) -> str:
    """«27.10.2026 15:25 МСК» (или только дата). Часовой пояс всегда указан явно."""
    if not value:
        return "—"
    moment = to_msk(value)
    return moment.strftime("%d.%m.%Y %H:%M МСК") if time else moment.strftime("%d.%m.%Y")


def money(x: Decimal | str) -> str:
    x = Decimal(x)
    s = f"{x:,.2f}".replace(",", " ")
    return (s[:-3] if s.endswith(".00") else s.replace(".", ",")) + " ₽"


def pct(x: Decimal | str) -> str:
    return f"{Decimal(x).normalize():f}".replace(".", ",") + "%"
