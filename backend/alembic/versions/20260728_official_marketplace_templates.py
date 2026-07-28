"""versioned official marketplace templates from published flows"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260728_marketplace_templates"
down_revision = ("f2c1e683b036", "e8f1a2b3c4d5")
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("marketplace_templates", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("key", sa.String(120), nullable=False, unique=True), sa.Column("slug", sa.String(120), nullable=False, unique=True), sa.Column("name", sa.String(200), nullable=False), sa.Column("description", sa.Text()), sa.Column("category", sa.String(80), nullable=False), sa.Column("segment", sa.String(80), nullable=False), sa.Column("modality", sa.String(32), nullable=False), sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_marketplace_templates_slug", "marketplace_templates", ["slug"], unique=True)
    op.create_table("marketplace_template_versions", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("marketplace_templates.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.String(32), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("source_flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id", ondelete="RESTRICT"), nullable=False), sa.Column("source_flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="RESTRICT"), nullable=False), sa.Column("manifest", postgresql.JSONB(), nullable=False), sa.Column("nodes_snapshot", postgresql.JSONB(), nullable=False), sa.Column("edges_snapshot", postgresql.JSONB(), nullable=False), sa.Column("dependencies", postgresql.JSONB(), nullable=False), sa.Column("checksum", sa.String(64), nullable=False), sa.Column("validation_report", postgresql.JSONB(), nullable=False), sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("published_at", sa.DateTime()), sa.UniqueConstraint("template_id", "version", name="uq_marketplace_template_version"))
    op.create_index("ix_marketplace_template_versions_template_id", "marketplace_template_versions", ["template_id"])
    op.create_index("ix_marketplace_template_versions_status", "marketplace_template_versions", ["status"])
    op.create_index("ix_marketplace_template_versions_checksum", "marketplace_template_versions", ["checksum"])

def downgrade():
    op.drop_table("marketplace_template_versions")
    op.drop_table("marketplace_templates")
