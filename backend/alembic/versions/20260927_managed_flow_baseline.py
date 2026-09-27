"""add installation managed Flow baseline

Revision ID: 20260927_managed_flow
Revises: 20260927_assistant_config

Existing installations are intentionally not backfilled: without validated
provenance and an unchanged current version, managed state cannot be proven.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260927_managed_flow"
down_revision = "20260927_assistant_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_installation_flow_management",
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("marketplace_installations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("management_mode", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("managed_flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("managed_graph_checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("management_mode IN ('managed', 'customized', 'unknown', 'inconsistent')", name="ck_marketplace_flow_management_mode"),
        sa.CheckConstraint("(managed_flow_version_id IS NULL) = (managed_graph_checksum IS NULL)", name="ck_marketplace_flow_management_baseline_pair"),
        sa.UniqueConstraint("flow_id", name="uq_marketplace_flow_management_flow"),
    )
    op.create_index("ix_marketplace_flow_management_version", "marketplace_installation_flow_management", ["managed_flow_version_id"])


def downgrade():
    op.drop_index("ix_marketplace_flow_management_version", table_name="marketplace_installation_flow_management")
    op.drop_table("marketplace_installation_flow_management")
