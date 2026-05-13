"""fix contacts tags_json and crm projection columns

Revision ID: 20260513_fix_contacts_tags_json
Revises: 20260513_contacts_crm_attributes
Create Date: 2026-05-13
"""

from alembic import op


revision = "20260513_fix_contacts_tags_json"
down_revision = "20260513_contacts_crm_attributes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags_json JSONB DEFAULT '[]'::jsonb;")
    op.execute(
        """
        UPDATE contacts
        SET tags_json = COALESCE(tags_json, tags, '[]'::jsonb)
        WHERE tags_json IS NULL;
        """
    )

    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_order_id VARCHAR;")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS city VARCHAR;")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS company VARCHAR;")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS plan VARCHAR;")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lifecycle_stage VARCHAR;")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS notes TEXT;")


def downgrade() -> None:
    # intentionally non-destructive for production compatibility
    pass
