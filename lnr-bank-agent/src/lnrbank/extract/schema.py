"""Схема ответа модели и проверка извлечённых значений по словарю параметров."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from lnrbank.config import Parameter

NA = "н/д"
NUMERIC_UNITS = {"% годовых", "%", "₽", "мес", "дней", "шт", "п.п."}
BOOL_VALUES = {"да": "yes", "нет": "no", "yes": "yes", "no": "no", "true": "yes", "false": "no"}


class LLMItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    parameter: str
    value: str
    unit: str = ""
    condition: str = ""
    evidence: str
    confidence: str = Field(default="medium", pattern="^(high|medium|low)$")


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[LLMItem]


def json_schema() -> dict:
    return LLMResponse.model_json_schema()


def normalize_value(raw: str, spec: Parameter) -> str | None:
    """Возвращает значение в каноническом виде или None, если оно не подходит под единицу."""
    value = raw.strip()
    if value.casefold() == NA:
        return NA
    if spec.unit in NUMERIC_UNITS:
        num = value.replace(" ", "").replace(" ", "").replace(",", ".").rstrip("%₽")
        try:
            number = Decimal(num)
        except InvalidOperation:
            return None
        if not number.is_finite():
            return None
        return format(number.normalize(), "f")
    if spec.unit == "bool":
        return BOOL_VALUES.get(value.casefold())
    return value or None
