"""saas flow engine core tables

Revision ID: 20260430_saas_flow_engine_core
Revises: 20260430_flow_guardrails_and_backups
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260430_saas_flow_engine_core"
down_revision = "20260430_flow_guardrails_and_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flow_versions", sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_flow_versions_is_published", "flow_versions", ["is_published"], unique=False)

    op.create_table(
        "flow_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_phone", sa.String(), nullable=False),
        sa.Column("current_node_id", sa.String(), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["flow_version_id"], ["flow_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flow_executions_flow_version_id", "flow_executions", ["flow_version_id"], unique=False)
    op.create_index("ix_flow_executions_user_phone", "flow_executions", ["user_phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_flow_executions_user_phone", table_name="flow_executions")
    op.drop_index("ix_flow_executions_flow_version_id", table_name="flow_executions")
    op.drop_table("flow_executions")
    op.drop_index("ix_flow_versions_is_published", table_name="flow_versions")
    op.drop_column("flow_versions", "is_published")
