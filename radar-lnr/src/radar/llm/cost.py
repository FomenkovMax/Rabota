"""Подсчёт токенов и стоимости запуска. Цены (USD за 1 млн токенов) берутся из config/settings.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostTracker:
    prices: dict                                   # {"filter": {"input":..,"output":..}, "analyze": {...}}
    usage: dict = field(default_factory=lambda: {"filter": [0, 0], "analyze": [0, 0]})

    def add(self, stage: str, tokens_in: int, tokens_out: int) -> None:
        self.usage[stage][0] += tokens_in
        self.usage[stage][1] += tokens_out

    @property
    def tokens_in(self) -> int:
        return sum(u[0] for u in self.usage.values())

    @property
    def tokens_out(self) -> int:
        return sum(u[1] for u in self.usage.values())

    @property
    def cost_usd(self) -> float | None:
        """None, если цены не заданы (тогда честно пишем «н/д», а не 0)."""
        total = 0.0
        for stage, (tin, tout) in self.usage.items():
            p = self.prices.get(stage) or {}
            if p.get("input") is None or p.get("output") is None:
                if tin or tout:
                    return None
                continue
            total += tin / 1e6 * p["input"] + tout / 1e6 * p["output"]
        return total

    def summary(self) -> str:
        c = self.cost_usd
        cost = f"${c:.4f}" if c is not None else "н/д (задай цены в settings.yaml)"
        return (f"LLM: токены вход={self.tokens_in}, выход={self.tokens_out}; стоимость={cost}; "
                f"фильтр={self.usage['filter']}, разбор={self.usage['analyze']}")
