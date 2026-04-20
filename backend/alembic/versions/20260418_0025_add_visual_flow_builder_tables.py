"""add visual flow builder nodes and edges

Revision ID: 20260418_0025
Revises: 20260418_0024
Create Date: 2026-04-18 20:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260418_0025"
down_revision = "20260418_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "flow_nodes" not in tables:
        op.create_table(
            "flow_nodes",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("position_x", sa.Integer(), nullable=True),
            sa.Column("position_y", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flow_nodes_flow_id", "flow_nodes", ["flow_id"], unique=False)
        op.create_index("ix_flow_nodes_tenant_id", "flow_nodes", ["tenant_id"], unique=False)

    if "flow_edges" not in tables:
        op.create_table(
            "flow_edges",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("source", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("target", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("condition", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source"], ["flow_nodes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target"], ["flow_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flow_edges_flow_id", "flow_edges", ["flow_id"], unique=False)

    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "current_node_id" not in conversation_columns:
        op.add_column("conversations", sa.Column("current_node_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            "fk_conversations_current_node_flow_nodes",
            "conversations",
            "flow_nodes",
            ["current_node_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_current_node_flow_nodes", "conversations", type_="foreignkey")
    op.drop_column("conversations", "current_node_id")
    op.drop_index("ix_flow_edges_flow_id", table_name="flow_edges")
    op.drop_table("flow_edges")
    op.drop_index("ix_flow_nodes_tenant_id", table_name="flow_nodes")
    op.drop_index("ix_flow_nodes_flow_id", table_name="flow_nodes")
    op.drop_table("flow_nodes")
