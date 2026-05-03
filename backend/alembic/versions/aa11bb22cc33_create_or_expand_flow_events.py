"""create or expand flow_events

Revision ID: aa11bb22cc33
Revises: 543d193b055a
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'aa11bb22cc33'
down_revision = '543d193b055a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS flow_events (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL,
      conversation_id uuid NOT NULL,
      flow_id uuid NULL,
      flow_version_id uuid NULL,
      node_id uuid NULL,
      event_type varchar(40) NOT NULL,
      user_id varchar(128) NULL,
      metadata_json json NOT NULL DEFAULT '{}'::json,
      created_at timestamp NOT NULL DEFAULT now()
    )
    """)
    with op.batch_alter_table('flow_events') as b:
      for c,t in [
        ('flow_version_id', postgresql.UUID(as_uuid=True)),
        ('user_id', sa.String(length=128)),
        ('metadata_json', sa.JSON()),
      ]:
        try: b.add_column(sa.Column(c,t, nullable=True if c!='metadata_json' else False, server_default=sa.text("'{}'::json") if c=='metadata_json' else None))
        except Exception: pass

def downgrade() -> None:
    pass
