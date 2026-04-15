"""dedupe leads and enforce unique tenant+phone

Revision ID: 20260415_0013
Revises: 20260415_0012
Create Date: 2026-04-15 14:50:00
"""

from alembic import op


revision = "20260415_0013"
down_revision = "20260415_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM leads a
        USING leads b
        WHERE a.id < b.id
          AND a.phone = b.phone
          AND a.tenant_id = b.tenant_id;
        """
    )

    op.execute(
        """
        ALTER TABLE leads
        DROP CONSTRAINT IF EXISTS uq_leads_tenant_phone;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'unique_lead_phone'
            ) THEN
                ALTER TABLE leads
                ADD CONSTRAINT unique_lead_phone
                UNIQUE (phone, tenant_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leads
        DROP CONSTRAINT IF EXISTS unique_lead_phone;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_leads_tenant_phone'
            ) THEN
                ALTER TABLE leads
                ADD CONSTRAINT uq_leads_tenant_phone
                UNIQUE (tenant_id, phone);
            END IF;
        END $$;
        """
    )
