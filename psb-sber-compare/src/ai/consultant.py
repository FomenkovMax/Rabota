"""AI-консультант: краткий вывод по собранным цифрам.

Модель получает только факты из нашей базы — ставки, дельты, акции — и
отвечает на их основе. Это сознательное ограничение: модель не должна
досочинять условия банков по памяти, потому что её знания устаревают,
а цифры в отчёте идут первому лицу.

Поэтому:
  • в промпт кладём выжимку из последнего сбора, а не общий вопрос;
  • просим отвечать только по переданным данным;
  • если данных для вывода мало, модель обязана сказать об этом прямо,
    а не заполнить пробел правдоподобной выдумкой.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: Модель по умолчанию. Меняется переменной AI_MODEL: у посредников
#: набор моделей свой, и нужной там может просто не быть.
DEFAULT_MODEL = "claude-opus-5"


def model_name() -> str:
    return os.environ.get("AI_MODEL", "").strip() or DEFAULT_MODEL


def base_url() -> str:
    """Адрес API. Пусто — официальный Anthropic."""
    return os.environ.get("ANTHROPIC_BASE_URL", "").strip()

SYSTEM_PROMPT = """\
Ты — аналитик розничного бизнеса Сбербанка. Твой собеседник — руководитель \
ГОСБ, он принимает решения по продуктовой линейке.

Правила, которые важнее стиля:
1. Отвечай ТОЛЬКО по цифрам, которые переданы в сообщении. Своих знаний о \
ставках банков не привлекай: они устарели, а цена ошибки — неверное решение.
2. Если данных для вывода не хватает, так и скажи и назови, чего именно \
не хватает. Не заполняй пробел правдоподобным предположением.
3. Не выдумывай названия продуктов и условия, которых нет в данных.
4. Числа приводи ровно так, как они даны, с указанием банка.

Стиль: по-деловому, без воды и без канцелярита. Сначала вывод, потом \
обоснование. Максимум 250 слов. Разметку используй умеренно: короткие \
абзацы и списки, без заголовков верхнего уровня.\
"""


class ConsultantUnavailable(RuntimeError):
    """Нет ключа, нет библиотеки или API недоступен."""


@dataclass
class Advice:
    text: str
    model: str = DEFAULT_MODEL
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def usage_note(self) -> str:
        return f"{self.input_tokens}→{self.output_tokens} токенов"


def _client() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise ConsultantUnavailable(
            "Не установлена библиотека anthropic. Выполни: pip install anthropic"
        ) from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ConsultantUnavailable(
            "Не задан ANTHROPIC_API_KEY.\n"
            "Положи ключ в файл .env рядом с проектом или в переменные окружения."
        )

    url = base_url()
    if url:
        log.info("Обращаюсь к API по адресу %s", url)
        return anthropic.Anthropic(base_url=url)
    return anthropic.Anthropic()


def build_facts(comparisons: list[Any], segments: list[Any],
                changes: list[Any], *, region: str, banks: list[str]) -> str:
    """Выжимка из последнего сбора — единственный источник фактов для модели."""
    lines = [f"Регион: {region}", f"Банки в сравнении: {', '.join(banks)}", ""]

    if comparisons:
        lines.append("СРАВНЕНИЕ ПРОДУКТОВ (дельта = ставка Сбера минус ставка конкурента):")
        for c in comparisons:
            psb = f"{c.psb_rate:g}%" if c.psb_rate is not None else "нет данных"
            sber = f"{c.sber_rate:g}%" if c.sber_rate is not None else "нет данных"
            delta = f"{c.delta_rate:+g} п.п." if c.delta_rate is not None else "—"
            lines.append(f"  • {c.label} [{c.category}]: конкурент {psb}, "
                         f"Сбер {sber}, дельта {delta} — {c.reason}")
        lines.append("")

    if segments:
        lines.append("АКЦИИ ПО СЕГМЕНТАМ:")
        for s in segments:
            lines.append(f"  • {s.segment}: {s.headline}")
        lines.append("")

    important = [c for c in changes if c.get("severity") in ("high", "medium")]
    if important:
        lines.append("ИЗМЕНЕНИЯ ЗА НЕДЕЛЮ:")
        for c in important[:20]:
            delta = (f", дельта {c['delta']:+g} п.п." if c.get("delta") is not None else "")
            lines.append(f"  • [{c['bank']}] {c['title'][:90]}{delta}")
        lines.append("")

    if len(lines) <= 3:
        lines.append("Данных по сравнению нет — сбор не проводился или пары не настроены.")

    return "\n".join(lines)


DEFAULT_QUESTION = (
    "Дай короткий вывод для руководителя: где мы проигрываем сильнее всего, "
    "что из этого требует решения в первую очередь и какие есть варианты действий."
)


def ask(facts: str, question: str = "", *, effort: str = "high") -> Advice:
    """Задаёт вопрос модели по переданным фактам."""
    client = _client()
    import anthropic

    user_text = (
        f"Данные последнего сбора:\n\n{facts}\n\n"
        f"Вопрос: {question or DEFAULT_QUESTION}"
    )

    # Параметры adaptive thinking и effort появились недавно. Официальный
    # API их принимает, а посредник может работать на более старой версии
    # и ответить ошибкой. Поэтому при отказе по форме запроса повторяем
    # без них: лучше ответ попроще, чем неработающая кнопка.
    request = {
        "model": model_name(),
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
    }
    extras = {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }

    def call(payload: dict) -> Any:
        return client.messages.create(**payload)

    try:
        try:
            response = call({**request, **extras})
        except (anthropic.BadRequestError, TypeError) as exc:
            log.warning("Сервер не принял расширенные параметры (%s), "
                        "повторяю упрощённым запросом", str(exc)[:120])
            response = call(request)
    except anthropic.AuthenticationError as exc:
        raise ConsultantUnavailable("Ключ ANTHROPIC_API_KEY отклонён") from exc
    except anthropic.RateLimitError as exc:
        retry = exc.response.headers.get("retry-after", "60")
        raise ConsultantUnavailable(
            f"Превышен лимит запросов, попробуй через {retry} с"
        ) from exc
    except anthropic.NotFoundError as exc:
        raise ConsultantUnavailable(
            f"Модель «{model_name()}» недоступна по этому адресу.\n"
            "Посмотри список моделей у поставщика ключа и впиши нужную "
            "в переменную AI_MODEL."
        ) from exc
    except anthropic.APIStatusError as exc:
        raise ConsultantUnavailable(
            f"API вернул ошибку {exc.status_code}: {exc.message}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        target = base_url() or "api.anthropic.com"
        raise ConsultantUnavailable(f"Нет связи с {target}") from exc

    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "") or ""
        raise ConsultantUnavailable(f"Модель отклонила запрос. {detail}".strip())

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise ConsultantUnavailable("Модель вернула пустой ответ")

    usage = getattr(response, "usage", None)
    return Advice(
        text=text,
        model=model_name(),
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )


def available() -> bool:
    """Можно ли вообще обращаться к консультанту."""
    try:
        _client()
        return True
    except ConsultantUnavailable:
        return False
