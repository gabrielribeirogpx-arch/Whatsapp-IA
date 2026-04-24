"""add flow versions table and current pointer

Revision ID: 20260424_0034
Revises: 20260424_0033
Create Date: 2026-04-24 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260424_0034"
down_revision = "20260424_0033"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_fk(inspector, table_name: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "flow_versions" not in tables:
        op.create_table(
            "flow_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("nodes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("edges_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["flow_id"], ["flows.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flow_versions_flow_id", "flow_versions", ["flow_id"], unique=False)
    else:
        flow_versions_columns = {column["name"] for column in inspector.get_columns("flow_versions")}
        if "version_number" not in flow_versions_columns and "version" in flow_versions_columns:
            op.alter_column("flow_versions", "version", new_column_name="version_number")

    inspector = inspect(bind)
    if not _has_column(inspector, "flows", "current_version_id"):
        op.add_column("flows", sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True))

    inspector = inspect(bind)
    if not _has_fk(inspector, "flows", "fk_flows_current_version_id_flow_versions"):
        op.create_foreign_key(
            "fk_flows_current_version_id_flow_versions",
            "flows",
            "flow_versions",
            ["current_version_id"],
            ["id"],
        )

    inspector = inspect(bind)
    if not _has_index(inspector, "flows", "ix_flows_current_version_id"):
        op.create_index("ix_flows_current_version_id", "flows", ["current_version_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_index(inspector, "flows", "ix_flows_current_version_id"):
        op.drop_index("ix_flows_current_version_id", table_name="flows")

    inspector = inspect(bind)
    if _has_fk(inspector, "flows", "fk_flows_current_version_id_flow_versions"):
        op.drop_constraint("fk_flows_current_version_id_flow_versions", "flows", type_="foreignkey")

    inspector = inspect(bind)
    if _has_column(inspector, "flows", "current_version_id"):
        op.drop_column("flows", "current_version_id")

    inspector = inspect(bind)
    if "flow_versions" in set(inspector.get_table_names()):
        if _has_index(inspector, "flow_versions", "ix_flow_versions_flow_id"):
            op.drop_index("ix_flow_versions_flow_id", table_name="flow_versions")
        op.drop_table("flow_versions")
