"""release hidden WhatsApp phone number provider lock

Revision ID: 20260601_release_hidden_provider_phone
Revises: 20260530_whatsapp_phone_owner
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260601_release_hidden_provider_phone"
down_revision = "20260530_whatsapp_phone_owner"
branch_labels = None
depends_on = None

TARGET_PHONE_NUMBER_ID = "876969468828520"
HIDDEN_PROVIDER_ID = "bb2848cc-782f-4f59-a2b7-8860d3c9bc61"
HIDDEN_PROVIDER_TENANT_ID = "b0c1a7d5-587b-476f-89d1-5596c02dad5d"
REMEDIATION_ID = "20260601_release_hidden_provider_phone"
OWNERSHIP_MIGRATION_ID = "20260530_whatsapp_phone_owner"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tenant_whatsapp_providers"):
        return

    if bind.dialect.name == "postgresql":
        _release_target_phone_number_postgresql()
        _deduplicate_remaining_phone_numbers_postgresql()
        _ensure_phone_number_owner_index(inspector)
    else:
        _release_target_phone_number_portable()


def downgrade() -> None:
    # Data-only corrective migration. Re-linking the hidden provider would restore
    # the production lock, so downgrade intentionally leaves the release in place.
    return


def _ensure_phone_number_owner_index(inspector: sa.Inspector) -> None:
    existing_indexes = {
        item["name"] for item in inspector.get_indexes("tenant_whatsapp_providers")
    }
    if "uq_tenant_whatsapp_provider_phone_number_owner" not in existing_indexes:
        op.create_index(
            "uq_tenant_whatsapp_provider_phone_number_owner",
            "tenant_whatsapp_providers",
            ["phone_number_id"],
            unique=True,
            postgresql_where=sa.text(
                "phone_number_id IS NOT NULL AND btrim(phone_number_id) <> ''"
            ),
        )


def _release_target_phone_number_postgresql() -> None:
    op.execute(
        sa.text(
            """
            WITH blocking_providers AS (
                SELECT
                    id,
                    tenant_id,
                    phone_number_id,
                    metadata_json,
                    CASE
                        WHEN id = CAST(:hidden_provider_id AS uuid)
                         AND tenant_id = CAST(:hidden_provider_tenant_id AS uuid)
                        THEN TRUE
                        ELSE FALSE
                    END AS is_confirmed_hidden_provider
                FROM tenant_whatsapp_providers
                WHERE phone_number_id = :target_phone_number_id
                FOR UPDATE
            ), released AS (
                UPDATE tenant_whatsapp_providers p
                SET
                    phone_number_id = NULL,
                    is_active = FALSE,
                    status = 'disconnected',
                    metadata_json = COALESCE(p.metadata_json, '{}'::jsonb) || jsonb_build_object(
                        'previous_phone_number_id', p.phone_number_id,
                        'phone_number_id_released_at', NOW()::text,
                        'phone_number_id_release_reason', 'hidden_provider_lock_removed',
                        'hidden_provider', bp.is_confirmed_hidden_provider,
                        'hidden_provider_id', :hidden_provider_id,
                        'hidden_provider_tenant_id', :hidden_provider_tenant_id,
                        'ownership_migration', :ownership_migration_id,
                        'remediation', :remediation_id
                    ),
                    updated_at = NOW()
                FROM blocking_providers bp
                WHERE p.id = bp.id
                RETURNING p.id, p.tenant_id
            )
            UPDATE tenants t
            SET phone_number_id = NULL
            WHERE t.phone_number_id = :target_phone_number_id
              AND EXISTS (
                SELECT 1 FROM released r WHERE r.tenant_id = t.id
              )
            """
        ).bindparams(
            target_phone_number_id=TARGET_PHONE_NUMBER_ID,
            hidden_provider_id=HIDDEN_PROVIDER_ID,
            hidden_provider_tenant_id=HIDDEN_PROVIDER_TENANT_ID,
            ownership_migration_id=OWNERSHIP_MIGRATION_ID,
            remediation_id=REMEDIATION_ID,
        )
    )


def _deduplicate_remaining_phone_numbers_postgresql() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    phone_number_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY phone_number_id
                        ORDER BY
                            is_active DESC,
                            updated_at DESC NULLS LAST,
                            created_at DESC NULLS LAST,
                            id
                    ) AS rn
                FROM tenant_whatsapp_providers
                WHERE phone_number_id IS NOT NULL
                  AND btrim(phone_number_id) <> ''
            )
            UPDATE tenant_whatsapp_providers p
            SET
                phone_number_id = NULL,
                is_active = FALSE,
                status = 'disconnected',
                metadata_json = COALESCE(p.metadata_json, '{}'::jsonb) || jsonb_build_object(
                    'previous_phone_number_id', ranked.phone_number_id,
                    'phone_number_id_deduplicated_at', NOW()::text,
                    'remediation', :remediation_id
                ),
                updated_at = NOW()
            FROM ranked
            WHERE p.id = ranked.id
              AND ranked.rn > 1
            """
        ).bindparams(remediation_id=REMEDIATION_ID)
    )


def _release_target_phone_number_portable() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tenant_whatsapp_providers
            SET
                phone_number_id = NULL,
                is_active = FALSE,
                status = 'disconnected',
                updated_at = CURRENT_TIMESTAMP
            WHERE phone_number_id = :target_phone_number_id
            """
        ).bindparams(target_phone_number_id=TARGET_PHONE_NUMBER_ID)
    )
