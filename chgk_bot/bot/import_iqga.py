"""Импорт выбранных вопросов с iqga.me в базу бота.

Запуск (на сервере, внутри контейнера):
    docker compose exec chgk-bot python -m bot.import_iqga

Скачивает страницы пакетов (по одному запросу в 1.5 с), берёт только вопросы из bot/iqga_selected.json
и сохраняет их вместе с автором, пакетом и ссылкой. Это материалы авторов вопросов — для личной
тренировки команды; не публикуйте их и не используйте в платных продуктах без разрешения авторов."""
import json
import re
import sys
from pathlib import Path

from . import iqga
from .config import PKG_DIR
from .storage import QuestionBank

NOTE_WORDS = ("ответ", "числе", "падеж", "роде", "порядк", "уточнен", "упомин", "отклонен", "написани", "смыслу", "синоним", "искажен")


def clean_answer(s: str) -> str:
    return s.strip().rstrip(".").strip()


def convert(q: dict) -> dict:
    """Запись iqga -> формат базы бота."""
    accepted = [clean_answer(a) for a in q.get("accepted", []) if not any(w in a.lower() for w in NOTE_WORDS)]
    notes = [clean_answer(a) for a in q.get("accepted", []) if any(w in a.lower() for w in NOTE_WORDS)]
    explanation = q["comment"] or "Комментарий автора отсутствует."
    return {
        "text": q["text"],
        "answer": clean_answer(q["answer"]),
        "accepted": accepted,
        "accept_note": "; ".join(notes),
        "rejected": [clean_answer(a) for a in q.get("rejected", [])],
        "explanation": explanation,
        "author": q["author"],
        "source": q["source"],
        "pack_title": q["pack_title"],
        "url": q["url"],
        "tags": [q["pack_title"]],
        "difficulty": 2 if "Школьная" in q["pack_title"] else 3,
        "origin": "iqga.me",
    }


def run(bank: QuestionBank, selected: dict, fetch=iqga.fetch) -> tuple[int, int]:
    """Возвращает (добавлено, найдено). fetch подменяется в тестах."""
    found = added = 0
    for pack, ids in selected["packs"].items():
        page = fetch(f"/base/{pack}/")
        wanted = set(ids)
        items = [convert(q) for q in iqga.parse_pack(page, int(pack)) if q["iqga_id"] in wanted and not q["has_media"]]
        found += len(items)
        added += bank.add(items, update=True)
        print(f"пакет {pack}: найдено {len(items)} из {len(wanted)}")
    return added, found


def main() -> None:
    import os

    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    bank = QuestionBank(data_dir / "questions.json", seed=PKG_DIR / "seed_questions.json")
    selected = json.loads((PKG_DIR / "iqga_selected.json").read_text(encoding="utf-8"))
    added, found = run(bank, selected)
    print(f"Готово: добавлено {added}, найдено {found}, всего в базе {len(bank.items)}")
    if found == 0:
        sys.exit("Ничего не нашлось: возможно, сайт изменил разметку.")


if __name__ == "__main__":
    main()
