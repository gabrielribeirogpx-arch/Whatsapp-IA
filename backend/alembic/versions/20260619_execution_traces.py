"""create execution traces

Revision ID: 20260619_execution_traces
Revises: 20260619_pgvector
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260619_execution_traces"
down_revision: Union[str, Sequence[str], None] = "20260619_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_execution_traces_trace_id", "execution_traces", ["trace_id"], unique=False)
    op.create_index("ix_execution_traces_tenant_id", "execution_traces", ["tenant_id"], unique=False)
    op.create_index("ix_execution_traces_conversation_id", "execution_traces", ["conversation_id"], unique=False)
    op.create_index("ix_execution_traces_execution_id", "execution_traces", ["execution_id"], unique=False)
    op.create_index("ix_execution_traces_created_at", "execution_traces", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_execution_traces_created_at", table_name="execution_traces")
    op.drop_index("ix_execution_traces_execution_id", table_name="execution_traces")
    op.drop_index("ix_execution_traces_conversation_id", table_name="execution_traces")
    op.drop_index("ix_execution_traces_tenant_id", table_name="execution_traces")
    op.drop_index("ix_execution_traces_trace_id", table_name="execution_traces")
    op.drop_table("execution_traces")
