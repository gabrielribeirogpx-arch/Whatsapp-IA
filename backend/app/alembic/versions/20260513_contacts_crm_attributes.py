"""contacts crm attributes

Revision ID: 20260513_contacts_crm_attributes
Revises: 20260512_force_contacts_columns
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260513_contacts_crm_attributes'
down_revision = '20260512_force_contacts_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags_json JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_order_id VARCHAR")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS city VARCHAR")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS company VARCHAR")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS plan VARCHAR")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lifecycle_stage VARCHAR")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute("UPDATE contacts SET tags_json = '[]'::jsonb WHERE tags_json IS NULL")


def downgrade() -> None:
    op.drop_column('contacts', 'notes')
    op.drop_column('contacts', 'lifecycle_stage')
    op.drop_column('contacts', 'plan')
    op.drop_column('contacts', 'company')
    op.drop_column('contacts', 'city')
    op.drop_column('contacts', 'last_order_id')
    op.drop_column('contacts', 'tags_json')
