"""GigaChat через SDK `gigachat`. TLS проверяется CA-бандлом с корнем Минцифры."""

from __future__ import annotations

import json
import logging

from gigachat import GigaChat
from gigachat.models import Chat, Function, FunctionParameters, Messages, MessagesRole

from lnrbank.config import Secrets, Settings
from lnrbank.net.tls import ca_bundle_path

log = logging.getLogger(__name__)
FUNCTION_NAME = "report_values"


def pick_model(names: list[str]) -> str:
    """Старшая доступная модель: сначала Max, потом Pro, иначе первая."""
    for marker in ("Max", "Pro"):
        tagged = sorted(n for n in names if marker in n)
        if tagged:
            return tagged[-1]
    if not names:
        raise RuntimeError("GigaChat не вернул список моделей")
    return names[0]


class GigaChatProvider:
    def __init__(self, settings: Settings, secrets: Secrets, client=None) -> None:
        if client is None:
            if secrets.gigachat_credentials is None:
                raise RuntimeError("Нет GIGACHAT_CREDENTIALS в .env")
            client = GigaChat(
                credentials=secrets.gigachat_credentials.get_secret_value(),
                scope=secrets.gigachat_scope or "GIGACHAT_API_PERS",
                ca_bundle_file=str(ca_bundle_path(settings)),
                timeout=settings.llm.timeout_s,
            )
        self.client = client
        self.model = settings.llm.model or pick_model([m.id_ for m in client.get_models().data])
        self._mode = "response_format"

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        if self._mode == "response_format":
            try:
                return self._via_response_format(system, user, schema)
            except Exception as exc:  # noqa: BLE001 — режим помечен в SDK как beta
                log.warning(
                    "response_format не сработал (%s), переключаюсь на functions",
                    type(exc).__name__,
                )
                self._mode = "functions"
        return self._via_functions(system, user, schema)

    def _messages(self, system: str, user: str) -> list[Messages]:
        return [
            Messages(role=MessagesRole.SYSTEM, content=system),
            Messages(role=MessagesRole.USER, content=user),
        ]

    def _via_response_format(self, system: str, user: str, schema: dict) -> dict:
        resp = self.client.chat(
            Chat(
                model=self.model,
                messages=self._messages(system, user),
                temperature=0.0,
                response_format={"type": "json_schema", "schema": schema, "strict": True},
            )
        )
        return json.loads(resp.choices[0].message.content)

    def _via_functions(self, system: str, user: str, schema: dict) -> dict:
        resp = self.client.chat(
            Chat(
                model=self.model,
                messages=self._messages(system, user),
                temperature=0.0,
                functions=[
                    Function(
                        name=FUNCTION_NAME,
                        description="Сообщить найденные значения",
                        parameters=FunctionParameters.model_validate(schema),
                    )
                ],
                function_call={"name": FUNCTION_NAME},
            )
        )
        call = resp.choices[0].message.function_call
        if call is None:
            raise ValueError("Модель не вызвала функцию")
        return call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments)
