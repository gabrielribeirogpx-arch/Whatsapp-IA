"""tenant performance and idempotency hardening

Revision ID: 20260505_tenant_perf_idempotency
Revises: 20260502_add_flow_status_terminal
Create Date: 2026-05-05
"""

from alembic import op

revision = "20260505_tenant_perf_idempotency"
down_revision = "20260502_add_flow_status_terminal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_lookup
        ON conversations (tenant_id, phone_number, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_time
        ON messages (conversation_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_tenant_time
        ON messages (tenant_id, created_at)
        """
    )

    op.execute("ALTER TABLE processed_messages DROP CONSTRAINT IF EXISTS processed_messages_pkey")
    op.execute(
        """
        ALTER TABLE processed_messages
        ADD CONSTRAINT processed_messages_pkey PRIMARY KEY (tenant_id, message_id)
        """
    )
    op.execute(
        """
        ALTER TABLE processed_messages
        ADD CONSTRAINT unique_tenant_message UNIQUE (tenant_id, message_id)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE processed_messages DROP CONSTRAINT IF EXISTS unique_tenant_message")
    op.execute("ALTER TABLE processed_messages DROP CONSTRAINT IF EXISTS processed_messages_pkey")
    op.execute(
        """
        ALTER TABLE processed_messages
        ADD CONSTRAINT processed_messages_pkey PRIMARY KEY (message_id)
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_messages_tenant_time")
    op.execute("DROP INDEX IF EXISTS idx_messages_conversation_time")
    op.execute("DROP INDEX IF EXISTS idx_conversation_lookup")
