"""flow guardrails and backup columns

Revision ID: 20260430_flow_guardrails_and_backups
Revises: 20260430_flow_sessions_state
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260430_flow_guardrails_and_backups"
down_revision = "20260430_flow_sessions_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE flow_sessions ADD COLUMN IF NOT EXISTS user_identifier TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_flow_sessions_user ON flow_sessions(user_identifier)"
    )
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS snapshot JSONB")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_versions_tenant_id ON flow_versions(tenant_id)")


def downgrade() -> None:
    op.drop_constraint("fk_flow_versions_tenant_id_tenants", "flow_versions", type_="foreignkey")
    op.drop_index("ix_flow_versions_tenant_id", table_name="flow_versions")
    op.drop_column("flow_versions", "snapshot")
    op.drop_column("flow_versions", "tenant_id")
