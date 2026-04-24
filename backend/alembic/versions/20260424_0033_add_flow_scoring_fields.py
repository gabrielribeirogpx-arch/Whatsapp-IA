"""add flow scoring fields

Revision ID: 20260424_0033
Revises: 20260424_0032
Create Date: 2026-04-24 00:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260424_0033"
down_revision = "20260424_0032"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "flows", "keywords"):
        op.add_column("flows", sa.Column("keywords", sa.Text(), nullable=True))
    if not _has_column(inspector, "flows", "stop_words"):
        op.add_column("flows", sa.Column("stop_words", sa.Text(), nullable=True))
    if not _has_column(inspector, "flows", "priority"):
        op.add_column("flows", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))

    op.execute(sa.text("UPDATE flows SET priority = COALESCE(priority, 0)"))
    op.execute(sa.text("UPDATE flows SET keywords = COALESCE(keywords, trigger_value)"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "flows", "priority"):
        op.drop_column("flows", "priority")
    if _has_column(inspector, "flows", "stop_words"):
        op.drop_column("flows", "stop_words")
    if _has_column(inspector, "flows", "keywords"):
        op.drop_column("flows", "keywords")
