"""Pydantic-схемы ответа LLM (валидация JSON)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

CATEGORIES = {
    1: ("🏢", "Новая организация / заход в ЛНР"),
    2: ("🔄", "Изменения по действующей"),
    3: ("⚠️", "Ухудшение фин. состояния"),
    4: ("💰", "Инвестиции и инвестпроекты"),
    5: ("🏛", "РГС: решения и назначения"),
    6: ("🛡", "Заявления силовиков"),
    7: ("🤖", "Цифровизация и ИИ"),
    8: ("🏦", "Банки-конкуренты"),
}


class Organization(BaseModel):
    name: str
    inn_if_in_text: Optional[str] = None   # только если ИНН буквально есть в тексте
    region: Optional[str] = None


class Person(BaseModel):
    name: str
    position: Optional[str] = None


class FilterItem(BaseModel):
    i: int
    relevant: bool


class FilterResult(BaseModel):
    results: list[FilterItem]


class SameNews(BaseModel):
    same: bool


class Event(BaseModel):
    category: int = Field(ge=1, le=8)
    title: str
    summary: str
    organizations: list[Organization] = []
    persons: list[Person] = []
    amounts: list[str] = []                    # суммы как в тексте, напр. «1,2 млрд руб.»
    employees_mentioned: Optional[int] = None
    relevance_score: int = Field(ge=1, le=5)
    business_opportunity: Optional[str] = None
    source_urls: list[str] = []

    @field_validator("organizations", "persons", "amounts", "source_urls", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v
