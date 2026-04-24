"""add tenant settings columns

Revision ID: 20260424_0035
Revises: 20260424_0034
Create Date: 2026-04-24 21:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260424_0035"
down_revision = "20260424_0034"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "tenants", "webhook_url"):
        op.add_column("tenants", sa.Column("webhook_url", sa.String(length=500), nullable=True))

    inspector = inspect(bind)
    if not _has_column(inspector, "tenants", "webhook_status"):
        op.add_column(
            "tenants",
            sa.Column("webhook_status", sa.String(length=32), nullable=False, server_default="inactive"),
        )

    inspector = inspect(bind)
    if not _has_column(inspector, "tenants", "language"):
        op.add_column(
            "tenants",
            sa.Column("language", sa.String(length=16), nullable=False, server_default="pt-BR"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "tenants", "language"):
        op.drop_column("tenants", "language")

    inspector = inspect(bind)
    if _has_column(inspector, "tenants", "webhook_status"):
        op.drop_column("tenants", "webhook_status")

    inspector = inspect(bind)
    if _has_column(inspector, "tenants", "webhook_url"):
        op.drop_column("tenants", "webhook_url")
