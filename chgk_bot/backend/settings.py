"""Настройки бэкенда из переменных окружения (.env). Секреты в коде не хранятся."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ids(name: str) -> frozenset[int]:
    return frozenset(int(x) for x in os.getenv(name, "").replace(" ", "").split(",") if x.lstrip("-").isdigit())


@dataclass(frozen=True)
class Settings:
    database_url: str
    bot_token: str
    jwt_secret: str
    admin_id: int = 0
    allowed_ids: frozenset[int] = frozenset()
    allowed_chats: frozenset[int] = frozenset()
    public_host: str = ""
    think_seconds: int = 60
    team_answer_seconds: int = 20      # окно ответа капитана после минуты
    answer_grace_seconds: int = 30      # после минуты ещё столько секунд можно сдать ответ (как в чат-игре)
    init_data_max_age: int = 86400      # initData старше суток не принимаем
    token_ttl: int = 12 * 3600
    judge_model: str = "claude-haiku-4-5"
    judge_timeout: float = 10.0         # Mini App ждёт ИИ-судью недолго, дальше запасной режим
    steps_model: str = ""
    anthropic_key: str = ""
    anthropic_auth_mode: str = "x-api-key"
    dev_auth: bool = False              # ТОЛЬКО для локальной разработки: вход без Telegram
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    hide_min_answers: int = 6
    hide_lo: float = 0.10
    hide_hi: float = 0.90
    brand_file: Path = ROOT / "config" / "brand.json"


def load_settings() -> Settings:
    url = os.getenv("DATABASE_URL", "").strip()
    secret = os.getenv("JWT_SECRET", "").strip()
    if not url:
        raise SystemExit("Не задан DATABASE_URL")
    if not secret:
        raise SystemExit("Не задан JWT_SECRET (сгенерируй: openssl rand -hex 32)")
    return Settings(
        database_url=url,
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        jwt_secret=secret,
        admin_id=int(os.getenv("ADMIN_ID", "0") or 0),
        allowed_ids=_ids("ALLOWED_IDS"),
        allowed_chats=_ids("ALLOWED_CHATS"),
        public_host=os.getenv("PUBLIC_HOST", "").strip(),
        think_seconds=int(os.getenv("THINK_SECONDS", "60")),
        team_answer_seconds=int(os.getenv("TEAM_ANSWER_SECONDS", "20")),
        judge_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5").strip(),
        judge_timeout=float(os.getenv("MINIAPP_JUDGE_TIMEOUT", "10")),
        steps_model=os.getenv("STEPS_MODEL", "").strip(),
        anthropic_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_auth_mode=os.getenv("ANTHROPIC_AUTH_MODE", "x-api-key").strip(),
        dev_auth=os.getenv("DEV_AUTH", "").strip() == "1",
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
        hide_min_answers=int(os.getenv("HIDE_MIN_ANSWERS", "6")),
        hide_lo=float(os.getenv("HIDE_LO", "0.10")),
        hide_hi=float(os.getenv("HIDE_HI", "0.90")),
        brand_file=Path(os.getenv("BRAND_FILE", str(ROOT / "config" / "brand.json"))),
    )
