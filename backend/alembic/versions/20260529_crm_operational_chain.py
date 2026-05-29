"""crm operational chain fields

Revision ID: 20260529_crm_operational
Revises: 20260529_pipeline_sprint1
Create Date: 2026-05-29 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260529_crm_operational"
down_revision: Union[str, Sequence[str], None] = "20260529_pipeline_sprint1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if not _has_column("leads", "email"):
        op.add_column("leads", sa.Column("email", sa.String(), nullable=True))
    if not _has_column("leads", "status"):
        op.add_column("leads", sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
    if not _has_column("leads", "entered_stage_at"):
        op.add_column("leads", sa.Column("entered_stage_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False))
    if not _has_column("leads", "updated_at"):
        op.add_column("leads", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False))

    op.execute("UPDATE leads SET source = 'whatsapp' WHERE source IS NULL OR source = ''")
    op.execute("UPDATE leads SET status = 'active' WHERE status IS NULL OR status = ''")
    op.execute("UPDATE leads SET entered_stage_at = COALESCE(entered_stage_at, last_interaction, created_at, NOW())")
    op.execute("UPDATE leads SET updated_at = COALESCE(updated_at, last_interaction, created_at, NOW())")

    if not _has_column("pipeline_stages", "is_final_stage"):
        op.add_column("pipeline_stages", sa.Column("is_final_stage", sa.Boolean(), server_default=sa.text("false"), nullable=False))

    op.execute("""
    WITH ranked AS (
      SELECT id, tenant_id, ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY position DESC, created_at DESC, id DESC) AS rn
      FROM pipeline_stages
    )
    UPDATE pipeline_stages ps
    SET is_final_stage = (ranked.rn = 1)
    FROM ranked
    WHERE ps.id = ranked.id
    """)

    if not _has_index("pipeline_stages", "uq_pipeline_stages_one_final_per_tenant"):
        op.create_index(
            "uq_pipeline_stages_one_final_per_tenant",
            "pipeline_stages",
            ["tenant_id"],
            unique=True,
            postgresql_where=sa.text("is_final_stage IS TRUE"),
        )

    if not _has_index("leads", "ix_leads_tenant_status"):
        op.create_index("ix_leads_tenant_status", "leads", ["tenant_id", "status"])


def downgrade() -> None:
    if _has_index("leads", "ix_leads_tenant_status"):
        op.drop_index("ix_leads_tenant_status", table_name="leads")
    if _has_index("pipeline_stages", "uq_pipeline_stages_one_final_per_tenant"):
        op.drop_index("uq_pipeline_stages_one_final_per_tenant", table_name="pipeline_stages")
    for table_name, column_name in [
        ("pipeline_stages", "is_final_stage"),
        ("leads", "updated_at"),
        ("leads", "entered_stage_at"),
        ("leads", "status"),
        ("leads", "email"),
    ]:
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
