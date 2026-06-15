"""tenant ai settings

Revision ID: 20260615_tenant_ai_settings
Revises: 20260615_knowledge_sources_rag
Create Date: 2026-06-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260615_tenant_ai_settings"
down_revision = "20260615_knowledge_sources_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_ai_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="wazza_default"),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Numeric(4, 2), nullable=False, server_default="0.2"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="1200"),
        sa.Column("embedding_provider", sa.String(length=32), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenant_ai_settings_tenant_id", "tenant_ai_settings", ["tenant_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tenant_ai_settings_tenant_id", table_name="tenant_ai_settings")
    op.drop_table("tenant_ai_settings")
