"""add ai_mode to tenants

Revision ID: 20260415_0004
Revises: 20260407_0003
Create Date: 2026-04-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260415_0004"
down_revision = "20260407_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = inspector.get_table_names()

    if "tenants" not in tables:
        # Table does not exist yet → skip migration safely
        return

    columns = [col["name"] for col in inspector.get_columns("tenants")]

    if "ai_mode" not in columns:
        op.add_column("tenants", sa.Column("ai_mode", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = inspector.get_table_names()

    if "tenants" not in tables:
        return

    columns = [col["name"] for col in inspector.get_columns("tenants")]

    if "ai_mode" in columns:
        op.drop_column("tenants", "ai_mode")
