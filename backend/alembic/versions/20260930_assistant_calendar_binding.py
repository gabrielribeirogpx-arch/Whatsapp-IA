"""add server-owned assistant calendar binding

Revision ID: 20260930_calendar_binding
Revises: 20260929_native_calendar
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260930_calendar_binding"
down_revision = "20260929_native_calendar"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_marketplace_installations_tenant_id_id", "marketplace_installations", ["tenant_id", "id"])
    op.create_table(
        "assistant_calendar_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("integration_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("native_calendar_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("native_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("provider IN ('google_calendar', 'wazza_native')", name="ck_assistant_calendar_binding_provider"),
        sa.CheckConstraint("(provider = 'google_calendar' AND integration_connection_id IS NOT NULL AND native_calendar_id IS NULL AND native_resource_id IS NULL) OR (provider = 'wazza_native' AND integration_connection_id IS NULL AND native_calendar_id IS NOT NULL AND native_resource_id IS NOT NULL)", name="ck_assistant_calendar_binding_shape"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "installation_id"], ["marketplace_installations.tenant_id", "marketplace_installations.id"], ondelete="CASCADE", name="fk_assistant_calendar_binding_tenant_installation"),
        sa.ForeignKeyConstraint(["integration_connection_id"], ["integration_connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["native_calendar_id"], ["native_calendars.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["native_resource_id"], ["calendar_resources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_assistant_calendar_bindings_tenant_id_id"),
    )
    op.create_index("ix_assistant_calendar_bindings_tenant_id", "assistant_calendar_bindings", ["tenant_id"])


def downgrade():
    op.drop_table("assistant_calendar_bindings")
    op.drop_constraint("uq_marketplace_installations_tenant_id_id", "marketplace_installations", type_="unique")
