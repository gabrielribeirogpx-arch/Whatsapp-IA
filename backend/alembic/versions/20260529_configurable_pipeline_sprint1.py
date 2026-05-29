"""configurable pipeline sprint 1

Revision ID: 20260529_pipeline_sprint1
Revises: 20260529_lead_links
Create Date: 2026-05-29 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260529_pipeline_sprint1"
down_revision: Union[str, Sequence[str], None] = "20260529_lead_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {item["name"] for item in inspector.get_columns(table_name)}


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_unique_constraints(table_name) + inspector.get_check_constraints(table_name)
    constraints += inspector.get_foreign_keys(table_name)
    return constraint_name in {item.get("name") for item in constraints}


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_column("tenants", "workspace_profile"):
        op.add_column(
            "tenants",
            sa.Column("workspace_profile", sa.String(length=32), server_default="private_sales", nullable=False),
        )
    op.execute("UPDATE tenants SET workspace_profile = 'private_sales' WHERE workspace_profile IS NULL")
    if not _has_constraint("tenants", "ck_tenants_workspace_profile"):
        op.create_check_constraint(
            "ck_tenants_workspace_profile",
            "tenants",
            "workspace_profile IN ('private_sales', 'government')",
        )

    if not _has_table("pipeline_stages"):
        op.create_table(
            "pipeline_stages",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pipeline_stages_tenant_id_tenants"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_pipeline_stage_tenant_name"),
            sa.UniqueConstraint("tenant_id", "position", name="uq_pipeline_stage_tenant_position"),
        )
    if not _has_index("pipeline_stages", "ix_pipeline_stages_tenant_id"):
        op.create_index("ix_pipeline_stages_tenant_id", "pipeline_stages", ["tenant_id"])

    if not _has_column("leads", "stage_id"):
        op.add_column("leads", sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    if not _has_constraint("leads", "fk_leads_stage_id_pipeline_stages"):
        op.create_foreign_key(
            "fk_leads_stage_id_pipeline_stages",
            "leads",
            "pipeline_stages",
            ["stage_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_index("leads", "ix_leads_stage_id"):
        op.create_index("ix_leads_stage_id", "leads", ["stage_id"])


def downgrade() -> None:
    if _has_index("leads", "ix_leads_stage_id"):
        op.drop_index("ix_leads_stage_id", table_name="leads")
    if _has_constraint("leads", "fk_leads_stage_id_pipeline_stages"):
        op.drop_constraint("fk_leads_stage_id_pipeline_stages", "leads", type_="foreignkey")
    if _has_column("leads", "stage_id"):
        op.drop_column("leads", "stage_id")

    if _has_table("pipeline_stages"):
        op.drop_table("pipeline_stages")

    if _has_constraint("tenants", "ck_tenants_workspace_profile"):
        op.drop_constraint("ck_tenants_workspace_profile", "tenants", type_="check")
    if _has_column("tenants", "workspace_profile"):
        op.drop_column("tenants", "workspace_profile")
