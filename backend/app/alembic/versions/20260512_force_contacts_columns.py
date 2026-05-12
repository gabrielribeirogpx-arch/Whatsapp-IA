"""force contacts columns

Revision ID: 20260512_force_contacts_columns
Revises: 20260512_fix_contacts_missing_columns
"""

from alembic import op

revision = "20260512_force_contacts_columns"
down_revision = "20260512_fix_contacts_missing_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS first_name VARCHAR;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_name VARCHAR;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email VARCHAR;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'whatsapp';
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS opt_in_status VARCHAR DEFAULT 'unknown';
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMP;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS custom_fields_json JSONB DEFAULT '{}'::jsonb;
        ALTER TABLE contacts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT now();

        UPDATE contacts SET tags = '[]'::jsonb WHERE tags IS NULL;
        UPDATE contacts SET custom_fields_json = '{}'::jsonb WHERE custom_fields_json IS NULL;
        UPDATE contacts SET source = 'whatsapp' WHERE source IS NULL;
        UPDATE contacts SET opt_in_status = 'unknown' WHERE opt_in_status IS NULL;
        UPDATE contacts SET updated_at = now() WHERE updated_at IS NULL;
        UPDATE contacts SET last_interaction_at = COALESCE(last_interaction_at, last_message_at, created_at) WHERE last_interaction_at IS NULL;
        """
    )


def downgrade() -> None:
    pass
