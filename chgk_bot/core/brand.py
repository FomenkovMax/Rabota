"""Бренд игры и наград: меняется одной правкой config/brand.json, в коде названий нет."""
import json
from pathlib import Path

DEFAULT = {
    "game_name": "ЧГК-тренажёр",
    "short_name": "ЧГК",
    "teams": {"experts": "Знатоки", "viewers": "Телезрители"},
    "awards": {"owl": "Сова", "diamond_owl": "Бриллиантовая сова"},
}


def load_brand(path: str | Path | None) -> dict:
    brand = json.loads(json.dumps(DEFAULT))   # глубокая копия значений по умолчанию
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(brand.get(k), dict):
                brand[k].update(v)
            else:
                brand[k] = v
    return brand
