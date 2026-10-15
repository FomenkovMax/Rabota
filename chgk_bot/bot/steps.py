"""Разбор вопроса по шагам: зацепка -> вывод -> ... -> ответ. Строится по комментарию автора, без новых фактов."""
import html

from .llm import ask, extract_json

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
HOWS = {"логика", "гипотеза", "ассоциация", "перебор", "знание"}

SYSTEM = """Ты — тренер по «Что? Где? Когда?». Разбери вопрос на шаги рассуждения так, как это делает хорошая команда: зацепка → вывод.

Правила:
- Используй ТОЛЬКО текст вопроса, ответ и комментарий автора. Не добавляй новых фактов, дат, имён и не выдумывай.
- 3–6 шагов, последний шаг приводит к ответу.
- "clue" — короткая цитата или деталь из ТЕКСТА ВОПРОСА (до 12 слов). Реалию, которая работает на ответ, называй явно.
- "inference" — что из неё следует (одно предложение, простым языком).
- "how" — как команда делает этот шаг: логика (прямой вывод из текста) | гипотеза (правдоподобное предположение, которое проверяют дальше) | ассоциация (связь по сходству, аллюзия) | перебор (перебор вариантов по условию) | знание (нужен конкретный факт).
- "lesson" — одно предложение: чему учит вопрос (на какую зацепку стоит обращать внимание в похожих вопросах).

Верни только JSON: {"steps":[{"clue":"","inference":"","how":""}],"lesson":""}"""


async def make_steps(client, model: str, q: dict) -> dict | None:
    """Возвращает {"steps": [...], "lesson": "..."} или None, если не получилось."""
    prompt = (
        f"Вопрос: {q['text']}\nОтвет: {q['answer']}\n"
        f"Комментарий автора: {q.get('explanation') or '—'}"
    )
    try:
        data = extract_json(await ask(client, model, SYSTEM, prompt, max_tokens=900))
        steps = [
            {"clue": str(s.get("clue", "")).strip(), "inference": str(s.get("inference", "")).strip(),
             "how": str(s.get("how", "")).strip().lower()}
            for s in data.get("steps", []) if str(s.get("inference", "")).strip()
        ][:6]
        if not steps:
            return None
        return {"steps": steps, "lesson": str(data.get("lesson", "")).strip()}
    except Exception:
        return None


def render_steps(q: dict, data: dict | None) -> str:
    """HTML-текст для Telegram. Без данных — комментарий автора как запасной вариант."""
    head = f"🧩 <b>Разбор по шагам</b>\nОтвет: <b>{html.escape(q['answer'])}</b>\n"
    if not data:
        return head + f"\nШаги сейчас недоступны. Комментарий автора:\n{html.escape(q.get('explanation') or '—')}"
    lines = []
    for i, s in enumerate(data["steps"]):
        how = f" <i>({html.escape(s['how'])})</i>" if s.get("how") else ""
        clue = f"«{html.escape(s['clue'])}» → " if s.get("clue") else ""
        lines.append(f"{NUM[i]} {clue}{html.escape(s['inference'])}{how}")
    out = head + "\n" + "\n".join(lines)
    if data.get("lesson"):
        out += f"\n\n💡 <b>Что запомнить:</b> {html.escape(data['lesson'])}"
    return out + "\n\n<i>Шаги составлены автоматически по комментарию автора.</i>"
