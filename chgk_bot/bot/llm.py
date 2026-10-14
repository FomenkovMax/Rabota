"""Общие утилиты для вызовов Claude."""
import json
import re


def extract_json(text: str):
    """Достаёт первый JSON-объект/массив из ответа модели (она может обернуть его в ```)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("В ответе модели нет корректного JSON")


async def ask(client, model: str, system: str, user: str, max_tokens: int = 4000) -> str:
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "text", None))


def make_client(api_key: str, mode: str = "x-api-key"):
    """Клиент Anthropic. mode='bearer' — для провайдеров, ждущих заголовок Authorization: Bearer.
    Адрес берётся из ANTHROPIC_BASE_URL (SDK читает его сам)."""
    from anthropic import AsyncAnthropic

    if mode == "bearer":
        return AsyncAnthropic(api_key=None, auth_token=api_key)
    return AsyncAnthropic(api_key=api_key)
