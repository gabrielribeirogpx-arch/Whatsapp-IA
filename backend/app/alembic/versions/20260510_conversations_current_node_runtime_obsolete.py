"""mark conversations.current_node_id as runtime-obsolete

Revision ID: 20260510_conversations_current_node_runtime_obsolete
Revises: 20260507_processed_messages_tenant_message_unique
Create Date: 2026-05-10
"""

from alembic import op

revision = "20260510_conversations_current_node_runtime_obsolete"
down_revision = "20260507_processed_messages_tenant_message_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ALTER COLUMN current_node_id DROP NOT NULL")
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_current_node_id_fkey")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'conversations_current_node_id_fkey'
            ) THEN
                ALTER TABLE conversations
                ADD CONSTRAINT conversations_current_node_id_fkey
                FOREIGN KEY (current_node_id) REFERENCES flow_nodes(id);
            END IF;
        END
        $$;
        """
    )
