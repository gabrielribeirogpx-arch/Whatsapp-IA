"""add failed_messages table for queue dead letter

Revision ID: 20260424_0031
Revises: 20260424_0030
Create Date: 2026-04-24 18:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260424_0031"
down_revision = "20260424_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "failed_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("buttons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_failed_messages_tenant_id"), "failed_messages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_failed_messages_job_id"), "failed_messages", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_failed_messages_job_id"), table_name="failed_messages")
    op.drop_index(op.f("ix_failed_messages_tenant_id"), table_name="failed_messages")
    op.drop_table("failed_messages")
