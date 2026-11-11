"""LLM-клиент с двумя режимами (LLM_API_FORMAT): anthropic или openai. Оба принимают base_url прокси."""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Любая ошибка LLM-сервиса (текст — понятный человеку)."""


class LLMAuthError(LLMError):
    """Неверный ключ / нет доступа / гео-блок (401, 403)."""


class LLMBalanceError(LLMError):
    """Токены (баланс прокси) закончились — дальше платить нечем."""


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int


_BALANCE_WORDS = re.compile(r"insufficient|balance|quota|credit|out of tokens|баланс|недостаточно|закончил|лимит токен", re.I)


def _explain(status: int | None, detail: str) -> LLMError:
    # 402 Payment Required, либо 403/429 с текстом про баланс/квоту = токены закончились (а не «неверный ключ»)
    if status == 402 or (status in (403, 429) and _BALANCE_WORDS.search(detail or "")):
        return LLMBalanceError("токены закончились: баланс сервиса LLM исчерпан — пополни у продавца")
    if status == 401:
        return LLMAuthError("401: ключ LLM_API_KEY неверный или не подходит к этому LLM_BASE_URL")
    if status == 403:
        return LLMAuthError("403: доступ запрещён — возможен гео-блок или у ключа нет доступа к модели")
    if status == 404:
        return LLMError("404: не найден эндпоинт или модель — проверь LLM_BASE_URL и названия MODEL_*")
    if status == 429:
        return LLMError("429: превышен лимит запросов/баланс прокси")
    return LLMError(f"ошибка LLM ({status}): {detail[:200]}")


async def fetch_balance(base_url: str, api_key: str, bearer: bool = True, path: str = "/v1/balance",
                        client: httpx.AsyncClient | None = None) -> int | None:
    """Остаток токенов у прокси (GET <base>/v1/balance -> {"token_balance": N}). Нет такого адреса/ошибка -> None."""
    root = re.sub(r"/v1/?$", "", (base_url or "").rstrip("/"))
    headers = {"Authorization": f"Bearer {api_key}"} if bearer else {"x-api-key": api_key}
    own = client or httpx.AsyncClient(timeout=15)
    try:
        r = await own.get(root + path, headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
        for key in ("token_balance", "balance", "tokens", "remaining"):
            if isinstance(data.get(key), (int, float)):
                return int(data[key])
    except (httpx.HTTPError, ValueError, AttributeError):
        log.info("баланс у LLM-сервиса получить не удалось")
    finally:
        if client is None:
            await own.aclose()
    return None


class LLMClient(ABC):
    balance_path = "/v1/balance"

    @abstractmethod
    async def complete(self, model: str, system: str, user: str, max_tokens: int = 1500) -> LLMResult:
        ...

    async def get_balance(self) -> int | None:
        """Остаток токенов, если сервис это отдаёт; иначе None (тогда показываем «н/д»)."""
        return None


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, bearer: bool = True):
        import anthropic
        self._sdk = anthropic
        # Многие прокси выдают «ANTHROPIC_AUTH_TOKEN» — он уходит заголовком Authorization: Bearer
        auth = {"auth_token": api_key} if bearer else {"api_key": api_key}
        self.client = anthropic.AsyncAnthropic(base_url=base_url or None, max_retries=2, **auth)
        self._bal = (base_url, api_key, bearer)

    async def get_balance(self) -> int | None:
        return await fetch_balance(*self._bal, path=self.balance_path)

    async def complete(self, model, system, user, max_tokens=1500) -> LLMResult:
        try:
            r = await self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
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
        self._bal = (base_url, api_key, True)

    async def get_balance(self) -> int | None:
        return await fetch_balance(*self._bal, path=self.balance_path)

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
        return AnthropicClient(key, env.llm_base_url, bearer=env.llm_auth_style != "x-api-key")
    if fmt == "openai":
        return OpenAIClient(key, env.llm_base_url)
    raise LLMError(f"LLM_API_FORMAT должен быть anthropic или openai, сейчас: {fmt!r}")
