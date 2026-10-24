"""Логирование: единый формат (текст или JSON) и маскирование секретов в любых сообщениях."""

import json
import logging
import re
import sys

# Токен Telegram-бота (123456789:AA...), ключи OpenAI-подобного вида, значения Bearer-заголовков.
_PATTERNS = [
    (re.compile(r"(?<![0-9])\d{6,}:[A-Za-z0-9_-]{30,}"), "<telegram-token>"),  # в URL идёт сразу после «bot»
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "<api-key>"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{10,}"), r"\1<redacted>"),
]


def redact(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:  # трассировки тоже могут содержать URL с токеном
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_text or record.exc_info:
            data["exc"] = record.exc_text or redact(self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False)


# Сторонние библиотеки на INFO пишут сотни служебных строк (шаги рендеринга PDF, подмножества шрифтов, каждый HTTP-запрос).
NOISY = ("weasyprint", "fontTools", "PIL", "httpx", "httpcore", "asyncio")


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # на INFO шумные библиотеки приглушаем до WARNING; на DEBUG показываем всё, на WARNING и выше — наследуют общий уровень
    quiet = logging.WARNING if logging.DEBUG < root.level < logging.WARNING else logging.NOTSET
    for name in NOISY:
        logging.getLogger(name).setLevel(quiet)
