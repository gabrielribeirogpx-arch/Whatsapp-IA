"""add pipeline stages and lead kanban fields

Revision ID: 20260415_0014
Revises: 20260415_0013
Create Date: 2026-04-15 16:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260415_0014"
down_revision = "20260415_0013"
branch_labels = None
depends_on = None


DEFAULT_STAGES = [
    "Novo",
    "Qualificado",
    "Proposta",
    "Fechamento",
    "Ganho",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "pipeline_stages" not in inspector.get_table_names():
        op.create_table(
            "pipeline_stages",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_pipeline_stage_tenant_name"),
            sa.UniqueConstraint("tenant_id", "position", name="uq_pipeline_stage_tenant_position"),
        )

    inspector = inspect(bind)
    existing_pipeline_indexes = {index["name"] for index in inspector.get_indexes("pipeline_stages")}
    pipeline_tenant_index = op.f("ix_pipeline_stages_tenant_id")
    if pipeline_tenant_index not in existing_pipeline_indexes:
        op.create_index(pipeline_tenant_index, "pipeline_stages", ["tenant_id"], unique=False)

    op.add_column("leads", sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("leads", sa.Column("temperature", sa.String(length=16), nullable=False, server_default="cold"))
    op.add_column("leads", sa.Column("last_interaction", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_leads_stage_id"), "leads", ["stage_id"], unique=False)
    op.create_foreign_key("fk_leads_stage_id", "leads", "pipeline_stages", ["stage_id"], ["id"])

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    for index, stage_name in enumerate(DEFAULT_STAGES):
        op.execute(
            f"""
            INSERT INTO pipeline_stages (id, tenant_id, name, position, created_at)
            SELECT gen_random_uuid(), t.id, '{stage_name}', {index}, NOW()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM pipeline_stages ps
                WHERE ps.tenant_id = t.id
                  AND ps.name = '{stage_name}'
            );
            """
        )

    op.execute(
        """
        UPDATE leads
        SET stage_id = ps.id,
            last_interaction = COALESCE(leads.last_contact_at, NOW())
        FROM pipeline_stages ps
        WHERE leads.tenant_id = ps.tenant_id
          AND ps.position = 0
          AND leads.stage_id IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_leads_stage_id", "leads", type_="foreignkey")
    op.drop_index(op.f("ix_leads_stage_id"), table_name="leads")
    op.drop_column("leads", "last_interaction")
    op.drop_column("leads", "temperature")
    op.drop_column("leads", "stage_id")

    op.drop_index(op.f("ix_pipeline_stages_tenant_id"), table_name="pipeline_stages")
    op.drop_table("pipeline_stages")
