import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent


@dataclass(frozen=True)
class Settings:
    bot_token: str
    anthropic_key: str
    model: str
    admin_id: int
    data_dir: Path
    think_seconds: int = 60   # минута на обсуждение, как в игре
    answer_seconds: int = 30  # время, чтобы отправить ответ после минуты


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (см. .env.example)")
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        anthropic_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5").strip(),
        admin_id=int(os.getenv("ADMIN_ID", "0") or 0),
        data_dir=data_dir,
    )
