"""pgvector vector stores

Revision ID: 20260619_pgvector
Revises: 20260618_worker_dlq
Create Date: 2026-06-19
"""
from __future__ import annotations

from alembic import op

revision = "20260619_pgvector"
down_revision = "20260618_worker_dlq"
branch_labels = None
depends_on = None


PGVECTOR_DIMENSION = 1536


def _vector_type_sql() -> str:
    """Return the fixed pgvector type used by this migration.

    Migrations must be deterministic, so do not read PGVECTOR_DIMENSION from the
    runtime environment here. The application default is 1536 and the vector
    indexes below require a fixed vector(N) column.
    """
    return f"vector({PGVECTOR_DIMENSION})"


def _ensure_vector_column(table_name: str) -> None:
    op.execute(
        f"""
        ALTER TABLE {table_name}
        ALTER COLUMN embedding TYPE {_vector_type_sql()}
        USING embedding::{_vector_type_sql()}
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS document_chunk_embeddings (
            id UUID PRIMARY KEY NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_id UUID NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
            chunk_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content_text TEXT NULL,
            embedding {_vector_type_sql()} NOT NULL,
            embedding_model TEXT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    _ensure_vector_column("document_chunk_embeddings")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS long_term_memory_embeddings (
            id UUID PRIMARY KEY NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            conversation_id UUID NULL REFERENCES conversations(id) ON DELETE SET NULL,
            contact_id UUID NULL REFERENCES contacts(id) ON DELETE SET NULL,
            external_user_id TEXT NULL,
            memory_id TEXT NULL,
            memory_type TEXT NULL,
            content_hash TEXT NOT NULL,
            memory_text TEXT NULL,
            embedding {_vector_type_sql()} NOT NULL,
            embedding_model TEXT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}',
            importance_score DOUBLE PRECISION NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            expires_at TIMESTAMP WITHOUT TIME ZONE NULL
        )
        """
    )
    _ensure_vector_column("long_term_memory_embeddings")

    for table, cols in {
        "document_chunk_embeddings": ["tenant_id", "source_id", "chunk_id", "content_hash", "created_at"],
        "long_term_memory_embeddings": ["tenant_id", "conversation_id", "contact_id", "external_user_id", "content_hash", "created_at"],
    }.items():
        for col in cols:
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table} ({col})")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_chunk_embeddings_vector "
        "ON document_chunk_embeddings USING ivfflat (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ltm_embeddings_vector "
        "ON long_term_memory_embeddings USING ivfflat (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ltm_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_doc_chunk_embeddings_vector")
    op.execute("DROP TABLE IF EXISTS long_term_memory_embeddings")
    op.execute("DROP TABLE IF EXISTS document_chunk_embeddings")
