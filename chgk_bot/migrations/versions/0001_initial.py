"""Начальная схема: игроки, команды, вопросы, попытки, соло-раунды

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JsonType = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("username", sa.String(100)),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("last_seen", sa.Float, nullable=False),
    )
    op.create_table(
        "teams",
        sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_table(
        "team_members",
        sa.Column("team_chat_id", sa.BigInteger, sa.ForeignKey("teams.chat_id"), primary_key=True),
        sa.Column("tg_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("joined_at", sa.Float, nullable=False),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("accepted", JsonType, nullable=False),
        sa.Column("rejected", JsonType, nullable=False),
        sa.Column("accept_note", sa.Text, nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("pack", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("difficulty", sa.SmallInteger, nullable=False),
        sa.Column("media", JsonType, nullable=False),
        sa.Column("steps", JsonType),
        sa.Column("origin", sa.String(50), nullable=False),
        sa.Column("hidden", sa.Boolean, nullable=False),
        sa.Column("extra", JsonType, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.BigInteger, nullable=False),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("answer", sa.Text),
        sa.Column("time_ms", sa.Integer),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("ts", sa.Float, nullable=False),
    )
    op.create_index("ix_attempts_actor_id", "attempts", ["actor_id"])
    op.create_index("ix_attempts_question_id", "attempts", ["question_id"])
    op.create_index("ix_attempts_ts", "attempts", ["ts"])
    op.create_index("ix_attempts_actor_question", "attempts", ["actor_id", "question_id"])
    op.create_table(
        "solo_rounds",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("question_id", sa.String(16), nullable=False),
        sa.Column("started_at", sa.Float, nullable=False),
        sa.Column("deadline_at", sa.Float, nullable=False),
        sa.Column("finished_at", sa.Float),
    )
    op.create_index("ix_solo_rounds_user_id", "solo_rounds", ["user_id"])


def downgrade() -> None:
    for t in ("solo_rounds", "attempts", "questions", "team_members", "teams", "users"):
        op.drop_table(t)
