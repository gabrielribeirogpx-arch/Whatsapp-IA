"""persist Runtime V2 session variables

Revision ID: 20260802_flow_v2_vars
Revises: 20260728_marketplace_templates
Create Date: 2026-08-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260802_flow_v2_vars"
down_revision = "20260728_marketplace_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_v2_sessions",
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("flow_v2_sessions", "variables")
