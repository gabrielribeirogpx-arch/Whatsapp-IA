"""Protect audit history from mutation and tenant cascade deletion.

Revision ID: 20260913_audit_p0
Revises: 20260828_appointment_policy
"""
from alembic import op
import sqlalchemy as sa

revision = "20260913_audit_p0"
down_revision = "20260828_appointment_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("audit_logs_tenant_id_fkey", type_="foreignkey")
        batch.create_foreign_key("audit_logs_tenant_id_fkey", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_constraint("audit_logs_tenant_id_fkey", type_="foreignkey")
        batch.create_foreign_key("audit_logs_tenant_id_fkey", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
