"""Add canonical message authorship and first session abandonment timestamp.

Revision ID: 20260926_dashboard_phase4
Revises: 20260926_dashboard_phase3

There is deliberately no backfill. Existing direction/status/updated timestamps
do not prove authorship or when abandonment occurred.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260926_dashboard_phase4"
down_revision = "20260926_dashboard_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("sender_type", sa.String(length=24), nullable=True))
        batch.create_check_constraint(
            "ck_messages_sender_type",
            "sender_type IS NULL OR sender_type IN ('customer', 'human_agent', 'ai', 'automation', 'system')",
        )
        batch.create_index("ix_messages_tenant_sender_created_at", ["tenant_id", "sender_type", "created_at"])
    with op.batch_alter_table("flow_sessions") as batch:
        batch.add_column(sa.Column("abandoned_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_flow_sessions_tenant_abandoned_at", ["tenant_id", "abandoned_at"])


def downgrade() -> None:
    with op.batch_alter_table("flow_sessions") as batch:
        batch.drop_index("ix_flow_sessions_tenant_abandoned_at")
        batch.drop_column("abandoned_at")
    with op.batch_alter_table("messages") as batch:
        batch.drop_index("ix_messages_tenant_sender_created_at")
        batch.drop_constraint("ck_messages_sender_type", type_="check")
        batch.drop_column("sender_type")
