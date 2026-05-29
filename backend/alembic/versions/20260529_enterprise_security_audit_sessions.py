"""enterprise security audit logs and user sessions

Revision ID: 20260529_enterprise_security
Revises: 20260529_account_hub_fields
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260529_enterprise_security"
down_revision = "20260529_account_hub_fields"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=True),
            sa.Column("entity_id", sa.String(length=120), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("ix_audit_logs_tenant_created_at", "audit_logs", ["tenant_id", "created_at"])
        op.create_index("ix_audit_logs_tenant_action", "audit_logs", ["tenant_id", "action"])
        op.create_index("ix_audit_logs_tenant_user", "audit_logs", ["tenant_id", "user_id"])

    if not _table_exists("user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_token_hash", sa.String(length=128), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("device_name", sa.String(length=160), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_user_sessions_token_hash", "user_sessions", ["session_token_hash"], unique=True)
        op.create_index("ix_user_sessions_tenant_user_revoked", "user_sessions", ["tenant_id", "user_id", "revoked_at"])


def downgrade() -> None:
    if _table_exists("user_sessions"):
        op.drop_index("ix_user_sessions_tenant_user_revoked", table_name="user_sessions")
        op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
        op.drop_table("user_sessions")
    if _table_exists("audit_logs"):
        op.drop_index("ix_audit_logs_tenant_user", table_name="audit_logs")
        op.drop_index("ix_audit_logs_tenant_action", table_name="audit_logs")
        op.drop_index("ix_audit_logs_tenant_created_at", table_name="audit_logs")
        op.drop_table("audit_logs")
