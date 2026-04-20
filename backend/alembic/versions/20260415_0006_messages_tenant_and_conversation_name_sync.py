"""sync messages.tenant_id and conversations.name

Revision ID: 20260415_0006
Revises: 20260415_0005
Create Date: 2026-04-15 01:00:00
"""

from alembic import op
from sqlalchemy import inspect


revision = "20260415_0006"
down_revision = "20260415_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    conversations_columns = [col["name"] for col in inspector.get_columns("conversations")]
    messages_columns = [col["name"] for col in inspector.get_columns("messages")]

    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS name VARCHAR")

    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id UUID")

    if "tenant_id" in conversations_columns and "tenant_id" in messages_columns:
        op.execute(
            """
            UPDATE messages AS m
            SET tenant_id = c.tenant_id
            FROM conversations AS c
            WHERE m.conversation_id = c.id
              AND m.tenant_id IS NULL
            """
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_tenant_id ON messages (tenant_id)")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM messages WHERE tenant_id IS NULL) THEN
                ALTER TABLE messages ALTER COLUMN tenant_id SET NOT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_messages_tenant_id", table_name="messages")
    op.drop_column("messages", "tenant_id")
