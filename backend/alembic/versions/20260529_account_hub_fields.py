"""add account hub fields to tenant users

Revision ID: 20260529_account_hub_fields
Revises: 20260527_add_password_reset_tokens
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20260529_account_hub_fields"
down_revision = "b5d5342d12c8"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in existing:
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing("tenant_users", sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
    _add_column_if_missing("tenant_users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("company", sa.String(length=150), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("job_title", sa.String(length=120), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("preferred_language", sa.String(length=16), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("timezone", sa.String(length=80), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("email_notifications_enabled", sa.Boolean(), server_default="true", nullable=False))
    _add_column_if_missing("tenant_users", sa.Column("whatsapp_notifications_enabled", sa.Boolean(), server_default="true", nullable=False))
    _add_column_if_missing("tenant_users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("tenant_users", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE tenant_users SET created_at = COALESCE(created_at, NOW()), updated_at = COALESCE(updated_at, NOW())")


def downgrade() -> None:
    for column_name in [
        "updated_at",
        "created_at",
        "password_changed_at",
        "last_login_at",
        "whatsapp_notifications_enabled",
        "email_notifications_enabled",
        "timezone",
        "preferred_language",
        "job_title",
        "company",
        "avatar_url",
        "status",
    ]:
        op.drop_column("tenant_users", column_name)
