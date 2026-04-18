"""add is_active to products

Revision ID: 20260418_0022
Revises: 20260418_0021
Create Date: 2026-04-18 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260418_0022"
down_revision = "20260418_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("products")}
    if "is_active" not in columns:
        op.add_column(
            "products",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade() -> None:
    op.drop_column("products", "is_active")
