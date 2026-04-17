"""add leads table

Revision ID: 20260415_0012
Revises: 20260415_0011
Create Date: 2026-04-15 10:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260415_0012"
down_revision = "20260415_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "leads" not in inspector.get_table_names():
        op.create_table(
            "leads",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("phone", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("stage", sa.String(), nullable=False, server_default="lead"),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_message", sa.Text(), nullable=True),
            sa.Column("last_contact_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "phone", name="uq_leads_tenant_phone"),
        )

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("leads")}
    tenant_index_name = op.f("ix_leads_tenant_id")
    phone_index_name = op.f("ix_leads_phone")
    if tenant_index_name not in existing_indexes:
        op.create_index(tenant_index_name, "leads", ["tenant_id"], unique=False)
    if phone_index_name not in existing_indexes:
        op.create_index(phone_index_name, "leads", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_leads_phone"), table_name="leads")
    op.drop_index(op.f("ix_leads_tenant_id"), table_name="leads")
    op.drop_table("leads")
