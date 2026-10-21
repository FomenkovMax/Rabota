"""Пакетная загрузка вопросов из JSON или CSV. Возвращает отчёт: сколько принято и какие строки отклонены (с причиной)."""
import csv
import io
import json

LIST_FIELDS = ("accepted", "rejected", "tags")


def _split(v: str) -> list[str]:
    return [x.strip() for x in str(v or "").split("|") if x.strip()]


def parse(fmt: str, content: str) -> tuple[list[dict], list[dict]]:
    """-> (годные записи, ошибки [{row, reason}]). Ничего не пишет в БД."""
    items: list[dict] = []
    errors: list[dict] = []
    if fmt == "json":
        try:
            data = json.loads(content)
        except ValueError as e:
            return [], [{"row": 0, "reason": f"Некорректный JSON: {e}"}]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return [], [{"row": 0, "reason": "Ожидался список вопросов"}]
        rows = list(enumerate(data, 1))
    elif fmt == "csv":
        rows = []
        for i, r in enumerate(csv.DictReader(io.StringIO(content.lstrip("﻿"))), 1):
            r = {k.strip(): (v or "") for k, v in r.items() if k}
            for f in LIST_FIELDS:
                if f in r:
                    r[f] = _split(r[f])
            rows.append((i, r))
    else:
        return [], [{"row": 0, "reason": "Формат должен быть json или csv"}]
    for i, r in rows:
        if not isinstance(r, dict):
            errors.append({"row": i, "reason": "Строка не объект"})
            continue
        missing = [k for k in ("text", "answer", "explanation") if not str(r.get(k, "")).strip()]
        if missing:
            errors.append({"row": i, "reason": "Не заполнено: " + ", ".join(missing)})
            continue
        if r.get("difficulty") not in (None, ""):
            try:
                r["difficulty"] = max(1, min(5, int(r["difficulty"])))
            except (TypeError, ValueError):
                errors.append({"row": i, "reason": "difficulty должно быть числом 1–5"})
                continue
        else:
            r.pop("difficulty", None)
        items.append(r)
    return items, errors
