"""flow snapshot integrity metadata

Revision ID: 20260603_flow_integrity
Revises: 20260601_release_hidden_phone
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260603_flow_integrity"
down_revision = "20260601_release_hidden_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flow_versions", sa.Column("nodes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("flow_versions", sa.Column("edges_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("flow_versions", sa.Column("nodes_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("flow_versions", sa.Column("edges_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("flow_versions", sa.Column("graph_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_flow_versions_graph_hash"), "flow_versions", ["graph_hash"], unique=False)
    op.execute("UPDATE flow_versions SET nodes_json = COALESCE(nodes_json, nodes), edges_json = COALESCE(edges_json, edges)")
    op.execute("UPDATE flow_versions SET nodes_count = COALESCE(jsonb_array_length(nodes_json), 0) WHERE jsonb_typeof(nodes_json) = 'array'")
    op.execute("UPDATE flow_versions SET edges_count = COALESCE(jsonb_array_length(edges_json), 0) WHERE jsonb_typeof(edges_json) = 'array'")
    op.execute("UPDATE flow_versions SET graph_hash = COALESCE(graph_hash, graph_checksum)")


def downgrade() -> None:
    op.drop_index(op.f("ix_flow_versions_graph_hash"), table_name="flow_versions")
    op.drop_column("flow_versions", "graph_hash")
    op.drop_column("flow_versions", "edges_count")
    op.drop_column("flow_versions", "nodes_count")
    op.drop_column("flow_versions", "edges_json")
    op.drop_column("flow_versions", "nodes_json")
