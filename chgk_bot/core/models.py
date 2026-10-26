"""Таблицы базы данных (PostgreSQL; в тестах SQLite). Схема меняется только через Alembic (папка migrations/)."""
import time

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# в PostgreSQL храним как JSONB (быстрые запросы), в SQLite — обычный JSON
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class User(Base):
    """Игрок Telegram. tg_id — настоящий id пользователя."""
    __tablename__ = "users"
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)      # аватарка из Telegram (initData.user.photo_url)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_seen: Mapped[float] = mapped_column(Float, default=time.time)


class Team(Base):
    """Команда = групповой чат Telegram (chat_id отрицательный)."""
    __tablename__ = "teams"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class TeamMember(Base):
    __tablename__ = "team_members"
    team_chat_id: Mapped[int] = mapped_column(ForeignKey("teams.chat_id"), primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    role: Mapped[str] = mapped_column(String(20), default="player")  # captain | player
    joined_at: Mapped[float] = mapped_column(Float, default=time.time)


class Question(Base):
    """Вопрос. id — те же 8 символов sha1 от текста, что и в MVP (ссылки в статистике не ломаются)."""
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    accepted: Mapped[list] = mapped_column(JsonType, default=list)
    rejected: Mapped[list] = mapped_column(JsonType, default=list)
    accept_note: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")           # разбор/комментарий автора
    source: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(Text, default="")
    pack: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(String(100), default="")
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3)
    media: Mapped[list] = mapped_column(JsonType, default=list)      # [{type: image|audio, url}]
    steps: Mapped[dict | None] = mapped_column(JsonType, nullable=True)  # кэш «разбора по шагам»
    origin: Mapped[str] = mapped_column(String(50), default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JsonType, default=dict)      # tags, facts, chgk, pattern
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Attempt(Base):
    """Единая таблица фактов для статистики: одна попытка ответить на вопрос.
    actor_id — id игрока (соло) или отрицательный id чата (командная игра), как в MVP."""
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question_id: Mapped[str] = mapped_column(String(16), index=True)
    score: Mapped[float] = mapped_column(Float)                      # 1 — взял, 0.5 — «почти», 0 — нет
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="solo")    # solo | team
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)


Index("ix_attempts_actor_question", Attempt.actor_id, Attempt.question_id)


class SoloRound(Base):
    """Открытый соло-вопрос с серверным дедлайном (чтобы таймер нельзя было «подкрутить» на клиенте)."""
    __tablename__ = "solo_rounds"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question_id: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[float] = mapped_column(Float)
    deadline_at: Mapped[float] = mapped_column(Float)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Game(Base):
    """Командная игра: состояние целиком в JSON (снимок на каждом переходе — после рестарта сервера игра продолжается)."""
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    team_id: Mapped[int] = mapped_column(BigInteger, index=True)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="active")   # active | finished
    state: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Award(Base):
    """Награда сезона (сова и т. п.): выдаётся один раз за закрытый месяц."""
    __tablename__ = "awards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    season: Mapped[str] = mapped_column(String(7))          # YYYY-MM
    kind: Mapped[str] = mapped_column(String(30))           # ключ из brand.awards
    points: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint("user_id", "season", "kind", name="uq_award"),)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    earned_at: Mapped[float] = mapped_column(Float, default=time.time)
