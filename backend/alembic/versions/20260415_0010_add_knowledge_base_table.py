"""add knowledge_base table

Revision ID: 20260415_0010
Revises: 20260415_0009
Create Date: 2026-04-15 05:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260415_0010"
down_revision = "20260415_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "knowledge_base" not in inspector.get_table_names():
        op.create_table(
            "knowledge_base",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("knowledge_base")}
    index_name = op.f("ix_knowledge_base_tenant_id")
    if index_name not in existing_indexes:
        op.create_index(index_name, "knowledge_base", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_base_tenant_id"), table_name="knowledge_base")
    op.drop_table("knowledge_base")
