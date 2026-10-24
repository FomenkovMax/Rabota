"""Единое форматирование чисел для бота и отчётов."""

from decimal import Decimal


def money(x: Decimal | str) -> str:
    x = Decimal(x)
    s = f"{x:,.2f}".replace(",", " ")
    return (s[:-3] if s.endswith(".00") else s.replace(".", ",")) + " ₽"


def pct(x: Decimal | str) -> str:
    return f"{Decimal(x).normalize():f}".replace(".", ",") + "%"
