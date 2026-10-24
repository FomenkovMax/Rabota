from bankintel.sources import cmr, generic, psb, vtb  # noqa: F401  (регистрируют адаптеры)
from bankintel.sources.base import BankAdapter, get_adapter, register_adapter

__all__ = ["BankAdapter", "get_adapter", "register_adapter"]
