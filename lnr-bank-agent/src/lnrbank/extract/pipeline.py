"""Конвейер извлечения: модель → схема → словарь параметров → проверка цитат → кэш.

Здесь собраны все защиты от выдумок (D-4, D-9, D-14): значение без дословной цитаты
из источника отбрасывается, а текст источника передаётся модели только как данные.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from lnrbank.config import Parameter
from lnrbank.extract.clean import evidence_in_source, normalize, trim_relevant
from lnrbank.extract.schema import NA, LLMItem, LLMResponse, json_schema, normalize_value
from lnrbank.storage.db import Storage

_VERSION = re.compile(r"<!--\s*version:\s*([\w.\-]+)\s*-->")


@dataclass
class ExtractedValue:
    parameter: str
    value: str
    unit: str
    condition: str
    evidence: str
    confidence: str


@dataclass
class ExtractionResult:
    values: list[ExtractedValue] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    status: str = "ok"
    reason: str = ""
    from_cache: bool = False


def _load_prompt(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    match = _VERSION.search(text.splitlines()[0] if text else "")
    if not match:
        raise ValueError(f"В первой строке {path.name} нет версии <!-- version: ... -->")
    return match.group(1), _VERSION.sub("", text, count=1).strip()


class Extractor:
    def __init__(
        self,
        provider,
        storage: Storage,
        parameters: dict[str, dict[str, Parameter]],
        prompts_dir: Path,
        max_chars: int = 12_000,
    ) -> None:
        self.provider = provider
        self.storage = storage
        self.parameters = parameters
        self.prompts_dir = prompts_dir
        self.max_chars = max_chars

    def _prompts(self, block: str) -> tuple[str, str, str]:
        sys_ver, system = _load_prompt(self.prompts_dir / "system.md")
        blk_ver, template = _load_prompt(self.prompts_dir / f"extract_{block}.md")
        listing = "\n".join(
            f"- {name} ({spec.unit}): {spec.description}"
            for name, spec in self.parameters[block].items()
        )
        return f"{sys_ver}/{blk_ver}", system, template.replace("{parameters}", listing)

    def extract(self, text: str, block: str) -> ExtractionResult:
        source = trim_relevant(text, self.max_chars)
        version, system, instructions = self._prompts(block)
        key = hashlib.sha256(normalize(source).encode()).hexdigest()
        model = self.provider.model

        cached = self.storage.cache_get(key, version, model)
        if cached is not None:
            result = self._validate(LLMResponse.model_validate(cached), block, source)
            result.from_cache = True
            return result

        user = f"{instructions}\n\n<source>\n{source}\n</source>"
        error = ""
        for attempt in range(2):
            prompt = (
                user
                if attempt == 0
                else (
                    f"{user}\n\nПредыдущий ответ содержал ошибку: {error}. "
                    "Верни JSON строго по схеме."
                )
            )
            try:
                raw = self.provider.complete_json(system, prompt, json_schema())
                parsed = LLMResponse.model_validate(raw)
            except ValidationError as exc:
                error = f"ответ не соответствует схеме ({exc.error_count()} ошибок)"
                continue
            except Exception as exc:  # noqa: BLE001 — сетевые и API-ошибки дают «н/д», а не падение
                error = f"{type(exc).__name__}: {exc}"[:200]
                continue
            self.storage.cache_put(key, version, model, parsed.model_dump())
            return self._validate(parsed, block, source)
        return ExtractionResult(status=NA, reason=error)

    def _validate(self, response: LLMResponse, block: str, source: str) -> ExtractionResult:
        result = ExtractionResult()
        allowed = self.parameters[block]
        for item in response.items:
            problem = self._problem(item, allowed, source)
            if problem:
                result.rejected.append(f"{item.parameter}: {problem}")
                continue
            spec = allowed[item.parameter]
            result.values.append(
                ExtractedValue(
                    parameter=item.parameter,
                    value=normalize_value(item.value, spec),
                    unit=spec.unit,
                    condition=item.condition,
                    evidence=normalize(item.evidence),
                    confidence=item.confidence,
                )
            )
        return result

    @staticmethod
    def _problem(item: LLMItem, allowed: dict[str, Parameter], source: str) -> str:
        spec = allowed.get(item.parameter)
        if spec is None:
            return "unknown_parameter"
        if item.unit and spec.unit not in ("text", "bool") and item.unit.strip() != spec.unit:
            return f"unit_mismatch ({item.unit} ≠ {spec.unit})"
        if normalize_value(item.value, spec) is None:
            return "bad_value"
        if not evidence_in_source(item.evidence, source):
            return "evidence_not_found"
        return ""
