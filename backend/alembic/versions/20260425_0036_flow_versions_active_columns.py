"""add active flag and canonical nodes/edges columns for flow versions

Revision ID: 20260425_0036
Revises: 3bbc2e0c6b1e
Create Date: 2026-04-25 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260425_0036"
down_revision = "3bbc2e0c6b1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("flow_versions")}

    if "nodes" not in columns:
        op.add_column("flow_versions", sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "edges" not in columns:
        op.add_column("flow_versions", sa.Column("edges", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "is_active" not in columns:
        op.add_column(
            "flow_versions",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    bind.execute(sa.text("UPDATE flow_versions SET nodes = COALESCE(nodes, nodes_json) WHERE nodes IS NULL"))
    bind.execute(sa.text("UPDATE flow_versions SET edges = COALESCE(edges, edges_json) WHERE edges IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("flow_versions")}

    if "is_active" in columns:
        op.drop_column("flow_versions", "is_active")
    if "edges" in columns:
        op.drop_column("flow_versions", "edges")
    if "nodes" in columns:
        op.drop_column("flow_versions", "nodes")
