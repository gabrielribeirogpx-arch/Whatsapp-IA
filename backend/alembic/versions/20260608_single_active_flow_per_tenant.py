"""enforce single active flow per tenant

Revision ID: 20260608_single_active_flow
Revises: 20260607_provider_connection
Create Date: 2026-06-08
"""

from alembic import op

revision = "20260608_single_active_flow"
down_revision = "20260607_provider_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Repair legacy tenants before the unique partial index is created. Keep the most
    # recently updated published active flow and deactivate every other active sibling.
    op.execute(
        """
        DO $$
        DECLARE
            conflict_record RECORD;
        BEGIN
            FOR conflict_record IN
                SELECT tenant_id, array_agg(id ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id ASC) AS flow_ids, count(*) AS active_count
                FROM flows
                WHERE is_active IS TRUE
                  AND COALESCE(is_deleted, FALSE) IS FALSE
                  AND deleted_at IS NULL
                GROUP BY tenant_id
                HAVING count(*) > 1
            LOOP
                RAISE WARNING '[MULTIPLE_ACTIVE_FLOWS] tenant_id=% active_count=% flow_ids=% action=dedupe_before_constraint',
                    conflict_record.tenant_id,
                    conflict_record.active_count,
                    conflict_record.flow_ids;
            END LOOP;
        END $$;
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY tenant_id
                    ORDER BY
                        (published_version_id IS NOT NULL) DESC,
                        updated_at DESC NULLS LAST,
                        created_at DESC NULLS LAST,
                        id ASC
                ) AS rn
            FROM flows
            WHERE is_active IS TRUE
              AND COALESCE(is_deleted, FALSE) IS FALSE
              AND deleted_at IS NULL
        )
        UPDATE flows f
        SET is_active = FALSE
        FROM ranked r
        WHERE f.id = r.id
          AND r.rn > 1;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_flows_single_active_per_tenant
        ON flows (tenant_id)
        WHERE is_active IS TRUE
          AND COALESCE(is_deleted, FALSE) IS FALSE
          AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_flows_single_active_per_tenant")
