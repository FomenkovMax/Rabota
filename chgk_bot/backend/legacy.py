"""Одноразовый перенос данных MVP (questions.json + stats.sqlite) в PostgreSQL.
Идемпотентен: вопросы грузятся, только если таблица пуста; попытки — только если таблица attempts пуста."""
import json
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import func, select

from core.models import Attempt, Question
from core.repo import QuestionRepo

log = logging.getLogger("backend.legacy")


def import_legacy(factory, data_dir: Path) -> dict:
    report = {"questions_added": 0, "questions_skipped": 0, "attempts_added": 0, "attempts_skipped": 0}
    data_dir = Path(data_dir)
    qfile, sfile = data_dir / "questions.json", data_dir / "stats.sqlite"
    with factory() as s:
        no_questions = (s.scalar(select(func.count()).select_from(Question)) or 0) == 0
        no_attempts = (s.scalar(select(func.count()).select_from(Attempt)) or 0) == 0

    if no_questions and qfile.exists():
        items = json.loads(qfile.read_text(encoding="utf-8"))
        added = QuestionRepo(factory).add(items)
        report["questions_added"], report["questions_skipped"] = added, len(items) - added

    seed = Path(__file__).resolve().parent.parent / "bot" / "seed_questions.json"
    if no_questions and report["questions_added"] == 0 and seed.exists():   # чистая установка: стартовые вопросы
        report["questions_added"] = QuestionRepo(factory).add(json.loads(seed.read_text(encoding="utf-8")))

    if no_attempts and sfile.exists():
        db = sqlite3.connect(sfile)
        try:
            rows = db.execute("SELECT user_id, qid, score, answer, ts, mode FROM results ORDER BY ts").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            db.close()
        with factory() as s:
            known = set(s.scalars(select(Question.id)))
            for uid, qid, score, answer, ts, mode in rows:
                if qid not in known:
                    report["attempts_skipped"] += 1
                    continue
                s.add(Attempt(actor_id=uid, question_id=qid, score=score, answer=answer,
                              mode=mode or "solo", ts=ts or 0))
                report["attempts_added"] += 1
            s.commit()
    log.info("Импорт данных MVP: %s", report)
    return report
