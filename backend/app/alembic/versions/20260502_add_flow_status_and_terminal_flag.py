"""add flow status and terminal flag

Revision ID: 20260502_add_flow_status_terminal
Revises: 20260430_add_fields_to_flow_sessions
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260502_add_flow_status_terminal"
down_revision = "20260430_add_fields_to_flow_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("status", sa.String(), nullable=False, server_default="draft"))
    op.create_index("ix_flows_status", "flows", ["status"], unique=False)
    op.add_column("flow_nodes", sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("flow_nodes", "is_terminal")
    op.drop_index("ix_flows_status", table_name="flows")
    op.drop_column("flows", "status")
