"""add flow crud columns

Revision ID: 20260424_0032
Revises: 20260424_0031
Create Date: 2026-04-24 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260424_0032"
down_revision = "20260424_0031"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "flows" not in tables:
        op.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS flows (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL REFERENCES tenants(id),
                    name TEXT NOT NULL,
                    description TEXT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    trigger_type TEXT NOT NULL DEFAULT 'default',
                    trigger_value TEXT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        inspector = inspect(bind)

    if not _has_column(inspector, "flows", "description"):
        op.add_column("flows", sa.Column("description", sa.Text(), nullable=True))
    if not _has_column(inspector, "flows", "is_active"):
        op.add_column("flows", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")))
    if not _has_column(inspector, "flows", "trigger_type"):
        op.add_column("flows", sa.Column("trigger_type", sa.Text(), nullable=False, server_default="default"))
    if not _has_column(inspector, "flows", "trigger_value"):
        op.add_column("flows", sa.Column("trigger_value", sa.Text(), nullable=True))
    if not _has_column(inspector, "flows", "version"):
        op.add_column("flows", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    if not _has_column(inspector, "flows", "updated_at"):
        op.add_column("flows", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")))

    op.execute(sa.text("UPDATE flows SET trigger_type = COALESCE(trigger_type, 'default')"))
    op.execute(sa.text("UPDATE flows SET is_active = COALESCE(is_active, TRUE)"))
    op.execute(sa.text("UPDATE flows SET version = COALESCE(version, 1)"))
    op.execute(sa.text("UPDATE flows SET updated_at = COALESCE(updated_at, NOW())"))

    inspector = inspect(bind)
    if not _has_index(inspector, "flows", "ix_flows_tenant_id"):
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_flows_tenant_id ON flows (tenant_id)"))
    if not _has_index(inspector, "flows", "ix_flows_trigger_type"):
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_flows_trigger_type ON flows (trigger_type)"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_index(inspector, "flows", "ix_flows_trigger_type"):
        op.drop_index("ix_flows_trigger_type", table_name="flows")

    inspector = inspect(bind)
    if _has_column(inspector, "flows", "updated_at"):
        op.drop_column("flows", "updated_at")
    if _has_column(inspector, "flows", "version"):
        op.drop_column("flows", "version")
    if _has_column(inspector, "flows", "trigger_value"):
        op.drop_column("flows", "trigger_value")
    if _has_column(inspector, "flows", "trigger_type"):
        op.drop_column("flows", "trigger_type")
    if _has_column(inspector, "flows", "is_active"):
        op.drop_column("flows", "is_active")
    if _has_column(inspector, "flows", "description"):
        op.drop_column("flows", "description")
