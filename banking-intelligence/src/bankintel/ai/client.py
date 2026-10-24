"""Клиенты LLM. Интерфейс один; реальная реализация (OpenAI) подключается лениво и не вызывается, пока AI не включён явно."""

import json
from typing import Protocol


class AiDisabled(Exception):
    pass


class LLMClient(Protocol):
    model: str

    async def extract(self, system: str, user: str, schema: dict) -> dict: ...


class OpenAIClient:
    """⚠️ Не проверялся на реальном API (нет ключа). Формат запроса — chat.completions с JSON-режимом; схема передаётся в подсказке."""

    def __init__(self, api_key: str, model: str, timeout_s: float = 90.0):
        from openai import AsyncOpenAI  # импорт лениво: пакет нужен только при включённом AI

        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_s)
        self.model = model

    async def extract(self, system: str, user: str, schema: dict) -> dict:
        resp = await self._client.chat.completions.create(
            model=self.model, temperature=0, response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": f"{system}\n\nСхема JSON:\n{json.dumps(schema, ensure_ascii=False)}"},
                {"role": "user", "content": user},
            ],
        )
        return json.loads(resp.choices[0].message.content or "{}")


def build_client(settings) -> LLMClient:
    if not settings.ai_enabled:
        raise AiDisabled("AI выключен (AI_ENABLED=false)")
    if settings.openai_api_key is None or not settings.ai_model:
        raise AiDisabled("нужны OPENAI_API_KEY и AI_MODEL")
    return OpenAIClient(settings.openai_api_key.get_secret_value(), settings.ai_model)
