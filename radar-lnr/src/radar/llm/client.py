"""LLM-клиент с двумя режимами (LLM_API_FORMAT): anthropic или openai. Оба принимают base_url прокси."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Любая ошибка LLM-сервиса (текст — понятный человеку)."""


class LLMAuthError(LLMError):
    """Неверный ключ / нет доступа / гео-блок (401, 403)."""


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int


def _explain(status: int | None, detail: str) -> LLMError:
    if status == 401:
        return LLMAuthError("401: ключ LLM_API_KEY неверный или не подходит к этому LLM_BASE_URL")
    if status == 403:
        return LLMAuthError("403: доступ запрещён — возможен гео-блок или у ключа нет доступа к модели")
    if status == 404:
        return LLMError("404: не найден эндпоинт или модель — проверь LLM_BASE_URL и названия MODEL_*")
    if status == 429:
        return LLMError("429: превышен лимит запросов/баланс прокси")
    return LLMError(f"ошибка LLM ({status}): {detail[:200]}")


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, model: str, system: str, user: str, max_tokens: int = 1500) -> LLMResult:
        ...


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, base_url: str):
        import anthropic
        self._sdk = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url or None, max_retries=2)

    async def complete(self, model, system, user, max_tokens=1500) -> LLMResult:
        try:
            r = await self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}], temperature=0)
        except self._sdk.APIStatusError as e:
            raise _explain(e.status_code, str(e)) from None
        except self._sdk.APIConnectionError as e:
            raise LLMError(f"нет соединения с LLM_BASE_URL: {e}") from None
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return LLMResult(text, r.usage.input_tokens, r.usage.output_tokens)


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, base_url: str):
        import openai
        self._sdk = openai
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url or None, max_retries=2)

    async def complete(self, model, system, user, max_tokens=1500) -> LLMResult:
        try:
            r = await self.client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except self._sdk.APIStatusError as e:
            raise _explain(e.status_code, str(e)) from None
        except self._sdk.APIConnectionError as e:
            raise LLMError(f"нет соединения с LLM_BASE_URL: {e}") from None
        u = r.usage
        return LLMResult(r.choices[0].message.content or "", getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))


def make_client(env) -> LLMClient:
    key = env.llm_api_key.get_secret_value()
    if not key:
        raise LLMAuthError("LLM_API_KEY пуст — заполни .env")
    fmt = env.llm_api_format.lower()
    if fmt == "anthropic":
        return AnthropicClient(key, env.llm_base_url)
    if fmt == "openai":
        return OpenAIClient(key, env.llm_base_url)
    raise LLMError(f"LLM_API_FORMAT должен быть anthropic или openai, сейчас: {fmt!r}")
