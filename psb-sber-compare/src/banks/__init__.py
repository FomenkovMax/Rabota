"""Адаптеры банков. Импорт модулей регистрирует их в реестре."""

from .base import BankAdapter, CollectResult, registry  # noqa: F401
from . import psb      # noqa: F401
from . import others   # noqa: F401

__all__ = ["BankAdapter", "CollectResult", "registry"]
