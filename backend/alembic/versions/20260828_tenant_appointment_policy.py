"""Add tenant-scoped clinic appointment policies.
Revision ID: 20260828_appointment_policy
Revises: 20260803_inbox_titles
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="20260828_appointment_policy"
down_revision="20260803_inbox_titles"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("tenant_appointment_policies", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("policy", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_tenant_appointment_policies_tenant_id", "tenant_appointment_policies", ["tenant_id"])
def downgrade():
    op.drop_index("ix_tenant_appointment_policies_tenant_id", table_name="tenant_appointment_policies")
    op.drop_table("tenant_appointment_policies")
