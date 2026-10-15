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
    team_answer_seconds: int = 20  # в командной игре капитан сдаёт ответ быстрее (как бланк в спортивном ЧГК)
    team_tours: int = 3
    team_per_tour: int = 12
    hide_min_answers: int = 6     # сколько ответов нужно, чтобы скрывать слишком лёгкие/сложные вопросы
    hide_lo: float = 0.10
    hide_hi: float = 0.90


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
        team_answer_seconds=int(os.getenv("TEAM_ANSWER_SECONDS", "20")),
        team_tours=int(os.getenv("TEAM_TOURS", "3")),
        team_per_tour=int(os.getenv("TEAM_PER_TOUR", "12")),
        hide_min_answers=int(os.getenv("HIDE_MIN_ANSWERS", "6")),
        hide_lo=float(os.getenv("HIDE_LO", "0.10")),
        hide_hi=float(os.getenv("HIDE_HI", "0.90")),
    )
