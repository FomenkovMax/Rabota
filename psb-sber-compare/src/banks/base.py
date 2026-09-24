"""Единый интерфейс сбора данных по банку.

Банки отдают данные по-разному, и это не стилистическая разница, а
разные технологии:

  ПСБ      SSR-состояние Angular в HTML — берётся обычным requests;
  Сбер     JS-челлендж F5 (bobcmn) — нужен настоящий браузер;
  ГенБанк  JS-челлендж Qrator — нужен настоящий браузер;
  ВТБ      SPA, контент приезжает отдельными XHR — нужен браузер;
  ЦМР      обычный сайт, часть условий в PDF-файлах.

Поэтому единого парсера не существует. Вместо него — адаптер на банк,
у всех один интерфейс, а оркестратор про их различия ничего не знает.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

log = logging.getLogger(__name__)


@dataclass
class CollectResult:
    """Что адаптер принёс за один запуск."""

    bank: str
    products: list[Any] = field(default_factory=list)
    promos: list[Any] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    collected_at: str = ""
    pages_visited: int = 0

    @property
    def summary(self) -> str:
        if not self.ok:
            return f"{self.bank}: сбор не удался — {self.error}"
        return (f"{self.bank}: продуктов {len(self.products)}, "
                f"акций {len(self.promos)}")


class BankAdapter(ABC):
    """Базовый адаптер банка.

    Наследники обязаны уметь одно: принести продукты и акции по рознице
    в заданном регионе. Всё остальное — детали конкретного сайта.
    """

    #: Короткий код банка, он же ключ в настройках: psb, sber, vtb…
    code: str = ""
    #: Как банк называется в отчёте.
    title: str = ""
    #: Чем берём данные — для честного сообщения в логе и в отчёте.
    strategy: str = ""
    #: Проверен ли адаптер на живых данных. Непроверенные помечаем в отчёте,
    #: чтобы никто не принял неподтверждённые цифры за факт.
    verified: bool = False

    def __init__(self, region: Any, settings: dict[str, Any] | None = None) -> None:
        self.region = region
        self.settings = settings or {}

    @abstractmethod
    def collect(self) -> CollectResult:
        """Собирает продукты и акции. Исключения наружу не выпускает."""

    def _result(self, **kwargs: Any) -> CollectResult:
        kwargs.setdefault("bank", self.title or self.code)
        kwargs.setdefault("collected_at", datetime.now().isoformat(timespec="seconds"))
        return CollectResult(**kwargs)

    def _failed(self, error: str) -> CollectResult:
        log.error("%s: %s", self.title or self.code, error)
        return self._result(ok=False, error=error)


class AdapterRegistry:
    """Реестр адаптеров: код банка → класс."""

    def __init__(self) -> None:
        self._items: dict[str, type[BankAdapter]] = {}

    def register(self, adapter: type[BankAdapter]) -> type[BankAdapter]:
        if not adapter.code:
            raise ValueError(f"У адаптера {adapter.__name__} не задан code")
        self._items[adapter.code] = adapter
        return adapter

    def get(self, code: str) -> type[BankAdapter] | None:
        return self._items.get(code)

    def codes(self) -> list[str]:
        return sorted(self._items)

    def titles(self) -> dict[str, str]:
        return {code: cls.title for code, cls in sorted(self._items.items())}

    def create(self, code: str, region: Any,
               settings: dict[str, Any] | None = None) -> BankAdapter:
        cls = self.get(code)
        if cls is None:
            raise KeyError(f"Неизвестный банк «{code}». "
                           f"Доступны: {', '.join(self.codes())}")
        return cls(region=region, settings=settings)

    def __iter__(self) -> Iterable[type[BankAdapter]]:
        return iter(self._items.values())


registry = AdapterRegistry()
