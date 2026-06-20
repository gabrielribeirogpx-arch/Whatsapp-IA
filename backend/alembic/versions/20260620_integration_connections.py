"""create generic integration connections

Revision ID: 20260620_integration_connections
Revises: 20260619_pgvector
Create Date: 2026-06-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260620_integration_connections"
down_revision = "20260619_execution_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("auth_type", sa.String(length=40), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_integration_connections_tenant_id", "integration_connections", ["tenant_id"])
    op.create_index("ix_integration_connections_tenant_provider", "integration_connections", ["tenant_id", "provider"])
    op.create_index("ix_integration_connections_tenant_status", "integration_connections", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_integration_connections_tenant_status", table_name="integration_connections")
    op.drop_index("ix_integration_connections_tenant_provider", table_name="integration_connections")
    op.drop_index("ix_integration_connections_tenant_id", table_name="integration_connections")
    op.drop_table("integration_connections")
