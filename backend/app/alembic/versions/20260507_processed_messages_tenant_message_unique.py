"""ensure processed_messages tenant/message uniqueness for idempotency

Revision ID: 20260507_processed_messages_tenant_message_unique
Revises: 20260507_flow_sessions_analytics
Create Date: 2026-05-07
"""

from alembic import op

revision = "20260507_processed_messages_tenant_message_unique"
down_revision = "20260507_flow_sessions_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE t.relname = 'processed_messages'
                  AND n.nspname = current_schema()
                  AND c.contype IN ('u', 'p')
                  AND c.conkey = ARRAY[
                      (SELECT attnum FROM pg_attribute WHERE attrelid = t.oid AND attname = 'tenant_id' AND NOT attisdropped),
                      (SELECT attnum FROM pg_attribute WHERE attrelid = t.oid AND attname = 'message_id' AND NOT attisdropped)
                  ]::smallint[]
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE t.relname = 'processed_messages'
                  AND n.nspname = current_schema()
                  AND i.indisunique
                  AND i.indkey = ARRAY[
                      (SELECT attnum FROM pg_attribute WHERE attrelid = t.oid AND attname = 'tenant_id' AND NOT attisdropped),
                      (SELECT attnum FROM pg_attribute WHERE attrelid = t.oid AND attname = 'message_id' AND NOT attisdropped)
                  ]::int2vector
            ) THEN
                CREATE UNIQUE INDEX uq_processed_messages_tenant_message
                ON processed_messages (tenant_id, message_id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_processed_messages_tenant_message")
