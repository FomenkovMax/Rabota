"""Сезоны: награды и ачивки

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "awards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("season", sa.String(7), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("points", sa.Float, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.UniqueConstraint("user_id", "season", "kind", name="uq_award"),
    )
    op.create_index("ix_awards_user_id", "awards", ["user_id"])
    op.create_table(
        "user_achievements",
        sa.Column("user_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("code", sa.String(30), primary_key=True),
        sa.Column("earned_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_achievements")
    op.drop_table("awards")
