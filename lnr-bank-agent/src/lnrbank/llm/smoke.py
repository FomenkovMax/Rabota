"""Живая проверка GigaChat: python -m lnrbank.llm.smoke [--golden]."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from lnrbank.config import load_parameters, load_secrets, load_settings
from lnrbank.extract.pipeline import Extractor
from lnrbank.llm.gigachat import GigaChatProvider
from lnrbank.storage.db import Storage

PROMPTS = Path(__file__).resolve().parents[1] / "extract" / "prompts"
SAMPLE = "Вклад «Пример». Ставка 14,2 % на 12 месяцев при открытии онлайн."


def main(argv: list[str]) -> int:
    if "--golden" in argv:
        print("Оценка на эталонном наборе появится в задаче 7.", file=sys.stderr)
        return 2
    settings, secrets = load_settings(), load_secrets()
    try:
        provider = GigaChatProvider(settings, secrets)
    except RuntimeError as exc:
        print(f"GigaChat недоступен: {exc}", file=sys.stderr)
        return 1
    models = [m.id_ for m in provider.client.get_models().data]
    print("Модели:", ", ".join(models))
    print("Выбрана:", provider.model)
    with tempfile.TemporaryDirectory() as tmp:
        store = Storage(Path(tmp) / "smoke.db", raw_dir=Path(tmp) / "raw")
        result = Extractor(provider, store, load_parameters(), PROMPTS).extract(SAMPLE, "DEP")
        store.close()
    for v in result.values:
        print(f"{v.parameter} = {v.value} {v.unit}  «{v.evidence}»")
    print("Отброшено:", result.rejected or "—", "| статус:", result.status, result.reason)
    ok = any(v.parameter == "rate_12m_online" and v.value == "14.2" for v in result.values)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
