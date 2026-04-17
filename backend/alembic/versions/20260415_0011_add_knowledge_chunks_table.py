"""add knowledge_chunks table

Revision ID: 20260415_0011
Revises: 20260415_0010
Create Date: 2026-04-15 09:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260415_0011"
down_revision = "20260415_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "knowledge_chunks" not in inspector.get_table_names():
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source", sa.String(length=255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("knowledge_chunks")}
    tenant_index_name = op.f("ix_knowledge_chunks_tenant_id")
    source_index_name = op.f("ix_knowledge_chunks_source")
    if tenant_index_name not in existing_indexes:
        op.create_index(tenant_index_name, "knowledge_chunks", ["tenant_id"], unique=False)
    if source_index_name not in existing_indexes:
        op.create_index(source_index_name, "knowledge_chunks", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_source"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
