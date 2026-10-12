"""Общие типы обогащения: карточка организации, результат поиска, интерфейс адаптера."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class OrgCard:
    """Карточка организации. Всё, чего нет в источнике, остаётся None / пустым (никаких догадок)."""
    inn: str | None = None
    ogrn: str | None = None
    kpp: str | None = None
    name_full: str | None = None
    name_short: str | None = None
    okved: str | None = None
    address: str | None = None
    director: str | None = None          # ЛПР (руководитель)
    director_post: str | None = None
    founders: list[str] = field(default_factory=list)
    employees: int | None = None         # среднесписочная численность
    status: str | None = None            # Действует / Ликвидируется / ...
    site: str | None = None              # только публичные контакты ОРГАНИЗАЦИИ
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OrgCard":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LookupResult:
    """status: found | needs_review | not_found | error | disabled"""
    status: str
    card: OrgCard | None = None
    candidates: list[OrgCard] = field(default_factory=list)   # топ-3 при needs_review
    message: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "card": self.card.to_dict() if self.card else None,
                "candidates": [c.to_dict() for c in self.candidates], "message": self.message}

    @classmethod
    def from_dict(cls, d: dict) -> "LookupResult":
        return cls(d["status"], OrgCard.from_dict(d["card"]) if d.get("card") else None,
                   [OrgCard.from_dict(c) for c in d.get("candidates", [])], d.get("message", ""))


class AdapterError(Exception):
    """Понятная человеку ошибка адаптера (ключ, лимит, сеть)."""


class Adapter(ABC):
    name: str

    @abstractmethod
    async def by_inn(self, inn: str) -> list[OrgCard]:
        ...

    @abstractmethod
    async def by_name(self, name: str, region: str | None = None) -> list[OrgCard]:
        ...
