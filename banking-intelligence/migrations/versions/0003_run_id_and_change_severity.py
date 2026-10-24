"""run id and change severity

Revision ID: 0003
Revises: 0002

Привязка документов, попыток загрузки, снимков и событий изменений к запуску сбора (collection_runs):
нужна, чтобы сравнивать «этот запуск» с «предыдущим» по каждому источнику.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = ("documents", "fetch_attempts", "product_snapshots", "change_events")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_run_id", "collection_runs", ["run_id"], ["id"])
            batch.create_index(f"ix_{table}_run_id", ["run_id"])
    with op.batch_alter_table("change_events") as batch:
        batch.add_column(sa.Column("severity", sa.String(length=10), server_default="info", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("change_events") as batch:
        batch.drop_column("severity")
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_run_id")
            batch.drop_constraint(f"fk_{table}_run_id", type_="foreignkey")
            batch.drop_column("run_id")
