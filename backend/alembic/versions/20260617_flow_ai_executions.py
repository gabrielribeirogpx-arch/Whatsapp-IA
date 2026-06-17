"""create flow ai executions

Revision ID: 20260617_flow_ai_executions
Revises: 20260617_ctx_rag
Create Date: 2026-06-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260617_flow_ai_executions"
down_revision = "20260617_ctx_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_ai_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=True),
        sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id"), nullable=True),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="success", nullable=False),
        sa.Column("input_size", sa.Integer(), nullable=True),
        sa.Column("output_size", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    for col in ("tenant_id", "conversation_id", "session_id", "created_at", "node_id", "node_type", "provider", "model", "status", "retrieval_mode", "confidence", "fallback_used"):
        op.create_index(f"ix_flow_ai_executions_{col}", "flow_ai_executions", [col])
    op.create_index("ix_flow_ai_executions_tenant_created", "flow_ai_executions", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("flow_ai_executions")
