"""Интерфейс LLM-провайдера.

Новый провайдер (YandexGPT, Ollama) — новый класс, конвейер не меняется.
"""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """Возвращает JSON-объект, по возможности соответствующий схеме."""
        ...
