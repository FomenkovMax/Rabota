"""Проверка LLM: ключ, base URL и доступность обеих моделей.  Запуск: uv run python scripts/check_llm.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from radar.config import get_env  # noqa: E402
from radar.llm.client import LLMAuthError, LLMError, make_client  # noqa: E402


async def main() -> int:
    env = get_env()
    print(f"Формат: {env.llm_api_format} | base_url: {env.llm_base_url or '(по умолчанию)'}")
    print(f"Ключ: {'задан (скрыт)' if env.llm_api_key.get_secret_value() else 'НЕ ЗАДАН'}")
    try:
        client = make_client(env)
    except LLMError as e:
        print("❌", e)
        return 1
    bad = 0
    for label, model in (("MODEL_FILTER", env.model_filter), ("MODEL_ANALYZE", env.model_analyze)):
        if not model:
            print(f"❌ {label} не задан в .env")
            bad += 1
            continue
        try:
            r = await client.complete(model, "Отвечай одним словом.", "Скажи: ок", max_tokens=20)
            print(f"✅ {label}={model}: ответ «{r.text.strip()[:30]}», токены {r.tokens_in}/{r.tokens_out}")
        except LLMAuthError as e:
            print(f"❌ {label}={model}: {e}")
            return 2  # ключ/гео — дальше проверять нет смысла
        except LLMError as e:
            print(f"❌ {label}={model}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
