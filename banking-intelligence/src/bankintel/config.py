from functools import lru_cache
from typing import Annotated
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: SecretStr | None = None
    # Пустой список = бот не отвечает никому (безопасное значение по умолчанию).
    allowed_telegram_ids: Annotated[list[int], NoDecode] = []
    database_url: str = "postgresql+asyncpg://bankintel:bankintel@localhost:5432/bankintel"
    raw_storage_dir: Path = PROJECT_ROOT / "data" / "raw"
    config_dir: Path = PROJECT_ROOT / "config"
    user_agent: str = "BankIntelBot/0.1 (research prototype; respects robots.txt)"
    # Дополнительный файл корневых сертификатов (PEM) для сайтов, чей CA отсутствует
    # в стандартном наборе. Проверка сертификатов никогда не отключается.
    extra_ca_bundle: Path | None = None
    fetch_min_interval_s: float = 2.0
    fetch_timeout_s: float = 20.0
    fetch_max_bytes: int = 10_000_000
    openai_api_key: SecretStr | None = None

    @field_validator("bot_token", "openai_api_key", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
