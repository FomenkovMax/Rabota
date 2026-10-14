"""Проверка ключа и модели без запуска бота: python -m bot.check_llm
Читает ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_MODE, CLAUDE_MODEL из .env.
Ключ нигде не печатается."""
import asyncio
import json
import os
import time

from dotenv import load_dotenv

from .config import PKG_DIR
from .judge import judge
from .llm import ask, make_client

load_dotenv()


async def try_mode(mode: str, model: str) -> bool:
    client = make_client(os.environ["ANTHROPIC_API_KEY"], mode)
    print(f"\n--- режим авторизации: {mode} ---")
    try:
        t0 = time.time()
        reply = await asyncio.wait_for(ask(client, model, "Отвечай одним словом.", "Столица Франции?", max_tokens=20), 45)
        print(f"✅ Ответ модели: {reply.strip()}  ({time.time() - t0:.1f} сек)")
    except Exception as e:
        print(f"❌ {type(e).__name__}: {str(e)[:300] or 'нет ответа за 45 сек (модель/провайдер молчит)'}")
        try:  # у многих посредников есть список моделей — подскажем реальные имена
            models = await client.models.list(limit=100)
            ids = [m.id for m in models.data]
            print("Доступные модели:", ", ".join(ids[:40]) or "—")
        except Exception:
            pass
        return False
    q = json.loads((PKG_DIR / "seed_questions.json").read_text(encoding="utf-8"))[0]
    for answer in ("антибиотик", "мороженое"):
        v = await judge(client, model, q, answer)
        print(f"Судья: ответ «{answer}» → {v.level} ({v.score}) — {v.comment}")
    return True


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Нет ANTHROPIC_API_KEY в .env")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    print("Адрес:", os.getenv("ANTHROPIC_BASE_URL", "официальный api.anthropic.com"))
    print("Модель:", model)
    for mode in (os.getenv("ANTHROPIC_AUTH_MODE", "x-api-key"), "bearer"):
        if await try_mode(mode, model):
            print(f"\n👍 Работает. Пропиши в .env: ANTHROPIC_AUTH_MODE={mode}")
            return
    print("\nНи один режим не сработал. Проверь ключ, адрес и имя модели (см. список выше).")


if __name__ == "__main__":
    asyncio.run(main())
