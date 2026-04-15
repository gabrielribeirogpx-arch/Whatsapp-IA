"""add knowledge_chunks table

Revision ID: 20260415_0011
Revises: 20260415_0010
Create Date: 2026-04-15 09:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260415_0011"
down_revision = "20260415_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.create_index(op.f("ix_knowledge_chunks_tenant_id"), "knowledge_chunks", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_knowledge_chunks_source"), "knowledge_chunks", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_source"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
