"""Данные из файла — запасной путь, когда сайт не отдаётся.

Сбор с сайта может не пойти: банк сменил вёрстку, проверка перестала
проходить, сайт лежит. Чтобы это не останавливало весь отчёт, любой банк
можно перевести на файл — выгрузку в Excel, CSV или JSON.

Включается в настройках банка:

    banks:
      sber:
        source: "data/sber.xlsx"

Как только `source` задан, адаптер берёт данные из файла и на сайт не
ходит. Такой банк всегда считается подтверждённым: содержимое файла —
ответственность того, кто его положил, а не парсера.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..sber.loader import load_sber
from .base import BankAdapter, CollectResult

log = logging.getLogger(__name__)


class FileAdapter(BankAdapter):
    """Читает продукты и акции банка из подготовленной выгрузки."""

    strategy = "выгрузка из файла"
    verified = True

    def __init__(self, base: BankAdapter, source: str | Path) -> None:
        super().__init__(region=base.region, settings=base.settings)
        self.code = base.code
        self.title = base.title
        self.source = Path(source)

    def collect(self) -> CollectResult:
        if not self.source.is_absolute():
            self.source = Path(__file__).resolve().parents[2] / self.source
        if not self.source.exists():
            return self._failed(f"файл выгрузки не найден: {self.source}")

        now = datetime.now().isoformat(timespec="seconds")
        region = self.settings.get("region_label", "")

        try:
            products, promos = load_sber(self.source, region=region,
                                         collected_at=now)
        except Exception as exc:                    # noqa: BLE001
            return self._failed(f"не удалось прочитать {self.source.name}: {exc}")

        if not products:
            return self._failed(f"в файле {self.source.name} не нашлось продуктов")

        # Загрузчик писал в поле банка «Сбер» — проставляем настоящий банк.
        for product in products:
            product.bank = self.title

        log.info("%s: из файла %s прочитано продуктов %s, акций %s",
                 self.title, self.source.name, len(products), len(promos))
        return self._result(products=products, promos=promos, collected_at=now)
