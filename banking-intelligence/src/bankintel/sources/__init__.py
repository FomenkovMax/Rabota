from bankintel.sources.base import BankAdapter, get_adapter, register_adapter
from bankintel.sources import generic  # noqa: F401  (регистрирует адаптер "generic")

__all__ = ["BankAdapter", "get_adapter", "register_adapter"]
