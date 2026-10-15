"""Общие утилиты для вызовов Claude."""
import json
import re


def extract_json(text: str):
    """Достаёт первый JSON-объект/массив из ответа модели (она может обернуть его в ```)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    # берём ту скобку, с которой JSON начинается раньше: объект {"steps":[...]} не должен превращаться в вложенный массив
    pairs = sorted((("[", "]"), ("{", "}")), key=lambda p: (text.find(p[0]) if p[0] in text else len(text)))
    for opener, closer in pairs:
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


def make_client(api_key: str, mode: str = "x-api-key", timeout: float = 90.0):
    """Клиент Anthropic. mode='bearer' — для провайдеров, ждущих заголовок Authorization: Bearer.
    Адрес берётся из ANTHROPIC_BASE_URL (SDK читает его сам)."""
    from anthropic import AsyncAnthropic

    # по умолчанию SDK ждёт до 10 минут и дважды повторяет — для бота это слишком долго
    if mode == "bearer":
        return AsyncAnthropic(api_key=None, auth_token=api_key, timeout=timeout, max_retries=1)
    return AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)
