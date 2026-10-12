"""Настройки: секреты из .env (pydantic-settings) + параметры из config/*.yaml."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (папка, где лежат config/ и channels.yaml)
# RADAR_HOME можно задать переменной (в Docker это /app); по умолчанию — папка проекта
ROOT = Path(os.environ.get("RADAR_HOME") or Path(__file__).resolve().parents[2])


def _ids(raw: str) -> list[int]:
    """'1, 2,3' -> [1, 2, 3]; пустая строка -> []."""
    return [int(x) for x in raw.replace(";", ",").split(",") if x.strip()]


class Env(BaseSettings):
    """Всё, что приходит из переменных окружения / .env. Секреты — SecretStr (не печатаются)."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    bot_token: SecretStr = SecretStr("")
    admin_user_id: int = 0
    allowed_user_ids: str = ""
    digest_chat_ids: str = ""

    llm_api_format: str = "anthropic"  # anthropic | openai
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_auth_style: str = "bearer"  # bearer | x-api-key (только для формата anthropic)
    model_filter: str = ""
    model_analyze: str = ""

    dadata_api_key: SecretStr = SecretStr("")
    dadata_secret: SecretStr = SecretStr("")

    data_dir: str = "./data"
    use_telethon: bool = False
    telethon_api_id: str = ""
    telethon_api_hash: SecretStr = SecretStr("")

    @property
    def allowed_ids(self) -> set[int]:
        # админ всегда имеет доступ
        return set(_ids(self.allowed_user_ids)) | ({self.admin_user_id} if self.admin_user_id else set())

    @property
    def chat_ids(self) -> list[int]:
        return _ids(self.digest_chat_ids)

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p = p if p.is_absolute() else ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_env() -> Env:
    return Env()


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8")) or {}


@lru_cache
def get_settings() -> dict:
    return load_yaml("config/settings.yaml")


def load_channels() -> list[dict]:
    return load_yaml("channels.yaml").get("channels", [])


def setup_logging(level: int = logging.INFO) -> None:
    """Лог в консоль + файл с ротацией (5 МБ × 5). Секреты сюда не попадают — их не логируем."""
    from logging.handlers import RotatingFileHandler

    log_dir = get_env().data_path / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in (logging.StreamHandler(),
              RotatingFileHandler(log_dir / "radar.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    # httpx пишет полные URL запросов — приглушаем
    logging.getLogger("httpx").setLevel(logging.WARNING)
