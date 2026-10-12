"""Импорт каналов из xlsx в channels.yaml.

Запуск:  uv run python scripts/import_xlsx.py config/Telegram_LNR_regional.xlsx
Берём строки со статусом «Подтверждён в поиске» и непустой ссылкой.
Каналы группы «Доп» из текущего channels.yaml сохраняются (их ты правишь руками).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl
import yaml

SHEET = "Региональные каналы ЛНР"
OK_STATUS = "Подтверждён в поиске"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "channels.yaml"

# Приоритет канала (1 = важнее) по разделу: влияет на порядок в логах и отчётах
SECTION_PRIORITY = {
    "Глава и Правительство": 1, "Министерства": 1, "Бизнес и инвестиции": 1,
    "Региональные органы федеральных ведомств": 1, "СМИ": 2, "Компании ЛНР": 1,
    "Муниципалитеты — города": 2, "Муниципалитеты — округа": 2,
}


def username_from_url(url: str) -> str | None:
    """https://t.me/agl_lnr -> agl_lnr (без / и ?)."""
    m = re.match(r"https?://t\.me/(?:s/)?([^/?#]+)", url.strip())
    return m.group(1) if m else None


def district_from_title(title: str, section: str) -> str | None:
    """«Администрация: Алчевск» -> «Алчевск» (для фильтра по району в дашборде)."""
    if section.startswith("Муниципалитеты") and ":" in title:
        return title.split(":", 1)[1].strip()
    return None


def main(xlsx: Path) -> None:
    ws = openpyxl.load_workbook(xlsx, data_only=True)[SHEET]
    rows = list(ws.iter_rows(values_only=True))[1:]  # без заголовка
    channels, skipped = [], []
    for _, section, title, url, subs, _desc, status in rows:
        uname = username_from_url(url) if url else None
        if status != OK_STATUS or not uname:
            skipped.append(title)
            continue
        item = {
            "username": uname, "title": title, "section": section,
            "priority": SECTION_PRIORITY.get(section, 3), "group": "xlsx",
        }
        if (d := district_from_title(title, section)):
            item["district"] = d
        channels.append(item)

    # Сохраняем уже существующие «Доп» каналы
    extra = []
    if OUT.exists():
        old = yaml.safe_load(OUT.read_text(encoding="utf-8")) or {}
        extra = [c for c in old.get("channels", []) if c.get("group") == "Доп"]

    data = {"channels": channels + extra}
    OUT.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Импортировано: {len(channels)}, доп.: {len(extra)}, пропущено без ссылки/статуса: {len(skipped)}")
    for s in skipped:
        print("  пропущен:", s)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config" / "Telegram_LNR_regional.xlsx")
