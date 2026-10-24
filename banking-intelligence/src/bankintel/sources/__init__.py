from bankintel.sources.base import BankAdapter, get_adapter, register_adapter
from bankintel.sources import generic, psb  # noqa: F401  (регистрируют адаптеры)

__all__ = ["BankAdapter", "get_adapter", "register_adapter"]
