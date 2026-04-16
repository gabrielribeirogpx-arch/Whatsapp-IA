"""dedupe conversations and enforce unique tenant+phone

Revision ID: 20260415_0007
Revises: 20260415_0006
Create Date: 2026-04-15 02:00:00
"""

from alembic import op


revision = "20260415_0007"
down_revision = "20260415_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM conversations a
        USING conversations b
        WHERE a.id < b.id
          AND a.phone_number = b.phone_number;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'conversations'
                  AND column_name = 'tenant_id'
            ) THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'unique_phone_tenant'
                ) THEN
                    ALTER TABLE conversations
                    ADD CONSTRAINT unique_phone_tenant
                    UNIQUE (phone_number, tenant_id);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
        DROP CONSTRAINT IF EXISTS unique_phone_tenant;
        """
    )
