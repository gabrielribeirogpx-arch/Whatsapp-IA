"""contact events crm

Revision ID: 20260514_contact_events_crm
Revises: 20260513_fix_contacts_tags_json
"""
from alembic import op

revision = "20260514_contact_events_crm"
down_revision = "20260513_fix_contacts_tags_json"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS contact_events (
      id UUID PRIMARY KEY,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      contact_id UUID NOT NULL REFERENCES contacts(id),
      type VARCHAR NOT NULL,
      title VARCHAR NOT NULL,
      description TEXT NULL,
      metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMP NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_contact_events_tenant_id ON contact_events(tenant_id);
    CREATE INDEX IF NOT EXISTS ix_contact_events_contact_id ON contact_events(contact_id);
    CREATE INDEX IF NOT EXISTS ix_contact_events_created_at ON contact_events(created_at);

    ALTER TABLE contacts ADD COLUMN IF NOT EXISTS score INTEGER NOT NULL DEFAULT 0;
    CREATE INDEX IF NOT EXISTS ix_contacts_last_interaction_at ON contacts(last_interaction_at);
    CREATE INDEX IF NOT EXISTS ix_contacts_score ON contacts(score);
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contact_events")
