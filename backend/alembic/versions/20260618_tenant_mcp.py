"""tenant mcp servers and tools

Revision ID: 20260618_tenant_mcp
Revises: 20260617_merge_ai
Create Date: 2026-06-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260618_tenant_mcp"
down_revision = "20260617_merge_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("server_url", sa.Text(), nullable=True),
        sa.Column("transport", sa.String(length=24), nullable=False, server_default="http"),
        sa.Column("encrypted_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenant_mcp_servers_tenant_id", "tenant_mcp_servers", ["tenant_id"])
    op.create_table(
        "tenant_mcp_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_mcp_servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(length=180), nullable=False),
        sa.Column("display_name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "server_id", "tool_name", name="uq_tenant_mcp_tool_name_per_server"),
    )
    op.create_index("ix_tenant_mcp_tools_tenant_id", "tenant_mcp_tools", ["tenant_id"])
    op.create_index("ix_tenant_mcp_tools_server_id", "tenant_mcp_tools", ["server_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_mcp_tools_server_id", table_name="tenant_mcp_tools")
    op.drop_index("ix_tenant_mcp_tools_tenant_id", table_name="tenant_mcp_tools")
    op.drop_table("tenant_mcp_tools")
    op.drop_index("ix_tenant_mcp_servers_tenant_id", table_name="tenant_mcp_servers")
    op.drop_table("tenant_mcp_servers")
