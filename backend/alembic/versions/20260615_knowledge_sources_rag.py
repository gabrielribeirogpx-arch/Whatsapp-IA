"""knowledge sources for rag

Revision ID: 20260615_knowledge_sources_rag
Revises: 20260615_flow_analytics_events
Create Date: 2026-06-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260615_knowledge_sources_rag"
down_revision = "20260615_flow_analytics_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_url", sa.String(length=1024), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_knowledge_sources_tenant_id", "knowledge_sources", ["tenant_id"])
    op.create_index("ix_knowledge_sources_tenant_created", "knowledge_sources", ["tenant_id", "created_at"])
    op.create_index("ix_knowledge_sources_tenant_type_status", "knowledge_sources", ["tenant_id", "type", "status"])
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.add_column(sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("title", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("embedding_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.add_column(sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.create_foreign_key("fk_knowledge_chunks_source_id", "knowledge_sources", ["source_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_knowledge_chunks_tenant_source", "knowledge_chunks", ["tenant_id", "source_id"])
    op.create_index("ix_knowledge_chunks_tenant_created", "knowledge_chunks", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_tenant_created", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_tenant_source", table_name="knowledge_chunks")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.drop_constraint("fk_knowledge_chunks_source_id", type_="foreignkey")
        batch.drop_column("metadata")
        batch.drop_column("embedding_json")
        batch.drop_column("title")
        batch.drop_column("chunk_index")
        batch.drop_column("source_id")
    op.drop_index("ix_knowledge_sources_tenant_type_status", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_created", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_id", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
