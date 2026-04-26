"""add published version pointer to flows

Revision ID: 20260426_0037
Revises: 20260425_0036
Create Date: 2026-04-26 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0037"
down_revision = "20260425_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("flows")}

    if "published_version_id" not in columns:
        op.add_column(
            "flows",
            sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    foreign_keys = {fk.get("constrained_columns", [None])[0] for fk in inspector.get_foreign_keys("flows")}
    if "published_version_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_flows_published_version_id_flow_versions",
            "flows",
            "flow_versions",
            ["published_version_id"],
            ["id"],
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("flows")}
    if "ix_flows_published_version_id" not in indexes:
        op.create_index("ix_flows_published_version_id", "flows", ["published_version_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {idx["name"] for idx in inspector.get_indexes("flows")}
    if "ix_flows_published_version_id" in indexes:
        op.drop_index("ix_flows_published_version_id", table_name="flows")

    foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("flows")}
    if "fk_flows_published_version_id_flow_versions" in foreign_keys:
        op.drop_constraint("fk_flows_published_version_id_flow_versions", "flows", type_="foreignkey")

    columns = {column["name"] for column in inspector.get_columns("flows")}
    if "published_version_id" in columns:
        op.drop_column("flows", "published_version_id")
