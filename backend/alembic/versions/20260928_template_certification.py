"""add marketplace template certification attestation

Revision ID: 20260928_template_cert
Revises: 20260927_managed_flow
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_template_cert"
down_revision = "20260927_managed_flow"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("marketplace_template_versions", sa.Column("certification_status", sa.String(24), nullable=False, server_default="uncertified"))
    op.add_column("marketplace_template_versions", sa.Column("certification_version", sa.String(64), nullable=True))
    op.add_column("marketplace_template_versions", sa.Column("candidate_checksum", sa.String(64), nullable=True))
    op.add_column("marketplace_template_versions", sa.Column("certified_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE marketplace_template_versions SET certification_status = 'legacy_unverified'")
    op.create_index("ix_marketplace_template_versions_certification_status", "marketplace_template_versions", ["certification_status"])
    op.create_index("ix_marketplace_template_versions_candidate_checksum", "marketplace_template_versions", ["candidate_checksum"])


def downgrade():
    op.drop_index("ix_marketplace_template_versions_candidate_checksum", table_name="marketplace_template_versions")
    op.drop_index("ix_marketplace_template_versions_certification_status", table_name="marketplace_template_versions")
    op.drop_column("marketplace_template_versions", "certified_at")
    op.drop_column("marketplace_template_versions", "candidate_checksum")
    op.drop_column("marketplace_template_versions", "certification_version")
    op.drop_column("marketplace_template_versions", "certification_status")
