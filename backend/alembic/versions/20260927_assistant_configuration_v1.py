"""add canonical assistant configuration v1

Revision ID: 20260927_assistant_config
Revises: 20260926_dashboard_phase4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260927_assistant_config"
down_revision = "20260926_dashboard_phase4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_installation_assistant_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("marketplace_installations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("configuration_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("configuration_version >= 1", name="ck_marketplace_assistant_config_version_positive"),
        sa.UniqueConstraint("installation_id", name="uq_marketplace_assistant_config_installation"),
    )


def downgrade():
    op.drop_table("marketplace_installation_assistant_configurations")
