"""Загрузка настроек: settings.yaml и parameters.yaml (без секретов) + секреты из окружения/.env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(os.environ.get("LNRBANK_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = PROJECT_ROOT / "config"
Block = Literal["DEP", "CARD", "LOAN", "MTG", "CHANNEL", "DAILY", "INV", "SEG"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Region(_Strict):
    name: str
    aliases: list[str]
    default_city: str
    city_aliases: dict[str, list[str]] = {}


class Bank(_Strict):
    name: str
    domains: list[str]
    home: str


class WatchlistBank(_Strict):
    code: str
    name: str
    offices_url: str


class Thresholds(_Strict):
    in_market_rate_pp: float
    in_market_amount_pct: float
    alert_rate_pp: float
    plausibility_deposit_over_key_pp: float


class LLM(_Strict):
    provider: Literal["gigachat"]
    model: str | None = None
    timeout_s: int = 60
    max_retries: int = 1


class Browser(_Strict):
    headless: bool = True
    delay_s: tuple[float, float] = (3, 6)
    locale: str = "ru-RU"
    timezone: str = "Europe/Moscow"
    # Путь к Chromium, если не тот, что ставит `playwright install` (переменная LNRBANK_CHROMIUM).
    executable_path: Path | None = None


class Storage(_Strict):
    db_path: Path
    raw_dir: Path
    out_dir: Path
    raw_retention_snapshots: int = Field(ge=1)


class TLS(_Strict):
    ca_bundle: Path
    check_hosts: list[str]


class Schedule(_Strict):
    cron: str


class Settings(_Strict):
    region: Region
    base_bank: str
    banks: dict[str, Bank]
    watchlist: list[WatchlistBank] = []
    blocks_mvp: list[Block]
    thresholds: Thresholds
    scenarios: dict[str, dict]
    llm: LLM
    browser: Browser
    storage: Storage
    tls: TLS
    schedule: Schedule

    def resolve(self, path: Path) -> Path:
        """Относительные пути из настроек считаются от корня проекта."""
        return path if path.is_absolute() else PROJECT_ROOT / path


class Parameter(_Strict):
    unit: str
    better: Literal["higher", "lower", "none"]
    description: str


class Secrets(BaseSettings):
    """Секреты только из окружения или .env — никогда из settings.yaml."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str | None = None  # None — GIGACHAT_API_PERS (физлица)
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    lnrbank_ca_bundle: Path | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _empty_is_unset(cls, value):
        # Пустая строка в .env (как в .env.example) значит «не задано», а не путь «.».
        return None if value == "" else value


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: Path | None = None) -> Settings:
    settings = Settings.model_validate(_read_yaml(path or CONFIG_DIR / "settings.yaml"))
    if settings.base_bank not in settings.banks:
        raise ValueError(f"base_bank '{settings.base_bank}' нет в banks")
    return settings


def load_parameters(path: Path | None = None) -> dict[str, dict[str, Parameter]]:
    raw = _read_yaml(path or CONFIG_DIR / "parameters.yaml")
    return {
        block: {name: Parameter.model_validate(spec) for name, spec in params.items()}
        for block, params in raw.items()
    }


def load_secrets() -> Secrets:
    return Secrets()
