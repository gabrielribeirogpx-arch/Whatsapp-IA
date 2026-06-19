"""pgvector vector stores

Revision ID: 20260619_pgvector
Revises: 20260618_worker_dlq
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260619_pgvector"
down_revision = "20260618_worker_dlq"
branch_labels = None
depends_on = None


def _vector_type() -> sa.Text:
    return sa.Text()


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_chunk_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("embedding", _vector_type(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("ALTER TABLE document_chunk_embeddings ALTER COLUMN embedding TYPE vector USING embedding::vector")
    op.create_table(
        "long_term_memory_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_user_id", sa.Text(), nullable=True),
        sa.Column("memory_id", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=True),
        sa.Column("embedding", _vector_type(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("importance_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.execute("ALTER TABLE long_term_memory_embeddings ALTER COLUMN embedding TYPE vector USING embedding::vector")
    for table, cols in {
        "document_chunk_embeddings": ["tenant_id", "source_id", "chunk_id", "content_hash", "created_at"],
        "long_term_memory_embeddings": ["tenant_id", "conversation_id", "contact_id", "external_user_id", "content_hash", "created_at"],
    }.items():
        for col in cols:
            op.create_index(f"ix_{table}_{col}", table, [col])
    op.execute("CREATE INDEX IF NOT EXISTS ix_doc_chunk_embeddings_vector ON document_chunk_embeddings USING ivfflat (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ltm_embeddings_vector ON long_term_memory_embeddings USING ivfflat (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ltm_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_doc_chunk_embeddings_vector")
    op.drop_table("long_term_memory_embeddings")
    op.drop_table("document_chunk_embeddings")
