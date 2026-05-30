"""enforce exclusive WhatsApp phone number provider ownership

Revision ID: 20260530_whatsapp_phone_owner
Revises: 20260514_contact_events_crm
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20260530_whatsapp_phone_owner"
down_revision = "20260514_contact_events_crm"
branch_labels = None
depends_on = None

TARGET_PHONE_NUMBER_ID = "876969468828520"
TARGET_TENANT_ID = "d89f177f-74dd-40e8-9496-7facaea76aaf"
TARGET_PROVIDER_ID = "465c1929-1708-4638-8008-1b7e70549c42"
RUNTIME_TENANT_ID = "b0c1a7d5-587b-476f-89d1-5596c02dad5d"
RUNTIME_PROVIDER_ID = "bb2848cc-782f-4f59-a2b7-8860d3c9bc61"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _remediate_known_duplicate()
        _deduplicate_remaining_provider_phone_numbers()
        op.create_index(
            "uq_tenant_whatsapp_provider_phone_number_owner",
            "tenant_whatsapp_providers",
            ["phone_number_id"],
            unique=True,
            postgresql_where=sa.text("phone_number_id IS NOT NULL AND btrim(phone_number_id) <> ''"),
        )
    else:
        op.create_index(
            "uq_tenant_whatsapp_provider_phone_number_owner",
            "tenant_whatsapp_providers",
            ["phone_number_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("uq_tenant_whatsapp_provider_phone_number_owner", table_name="tenant_whatsapp_providers")


def _remediate_known_duplicate() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tenant_whatsapp_providers
            SET
                is_active = FALSE,
                status = 'disconnected',
                phone_number_id = NULL,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object(
                    'phone_number_id_reassigned_to_tenant_id', :target_tenant_id,
                    'phone_number_id_reassigned_to_provider_id', :target_provider_id,
                    'phone_number_id_reassigned_at', NOW()::text,
                    'previous_phone_number_id', :phone_number_id,
                    'remediation', '20260530_whatsapp_phone_owner'
                ),
                updated_at = NOW()
            WHERE id = CAST(:runtime_provider_id AS uuid)
              AND tenant_id = CAST(:runtime_tenant_id AS uuid)
              AND phone_number_id = :phone_number_id
            """
        ).bindparams(
            phone_number_id=TARGET_PHONE_NUMBER_ID,
            target_tenant_id=TARGET_TENANT_ID,
            target_provider_id=TARGET_PROVIDER_ID,
            runtime_provider_id=RUNTIME_PROVIDER_ID,
            runtime_tenant_id=RUNTIME_TENANT_ID,
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE tenant_whatsapp_providers
            SET is_active = FALSE, updated_at = NOW()
            WHERE tenant_id = CAST(:target_tenant_id AS uuid)
              AND id <> CAST(:target_provider_id AS uuid)
              AND is_active = TRUE
            """
        ).bindparams(target_tenant_id=TARGET_TENANT_ID, target_provider_id=TARGET_PROVIDER_ID)
    )

    op.execute(
        sa.text(
            """
            UPDATE tenant_whatsapp_providers
            SET
                phone_number_id = :phone_number_id,
                is_active = TRUE,
                status = CASE WHEN status = 'token_expired' THEN 'connected' ELSE status END,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object(
                    'exclusive_phone_number_owner', TRUE,
                    'exclusive_phone_number_owner_at', NOW()::text,
                    'remediation', '20260530_whatsapp_phone_owner'
                ),
                updated_at = NOW()
            WHERE id = CAST(:target_provider_id AS uuid)
              AND tenant_id = CAST(:target_tenant_id AS uuid)
            """
        ).bindparams(
            phone_number_id=TARGET_PHONE_NUMBER_ID,
            target_provider_id=TARGET_PROVIDER_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE tenants
            SET phone_number_id = NULL
            WHERE id = CAST(:runtime_tenant_id AS uuid)
              AND phone_number_id = :phone_number_id
            """
        ).bindparams(runtime_tenant_id=RUNTIME_TENANT_ID, phone_number_id=TARGET_PHONE_NUMBER_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE tenants
            SET phone_number_id = :phone_number_id
            WHERE id = CAST(:target_tenant_id AS uuid)
              AND (phone_number_id IS NULL OR phone_number_id = '' OR phone_number_id = :phone_number_id)
            """
        ).bindparams(target_tenant_id=TARGET_TENANT_ID, phone_number_id=TARGET_PHONE_NUMBER_ID)
    )

    _migrate_runtime_records_to_owner()


def _migrate_runtime_records_to_owner() -> None:
    params = dict(runtime_tenant_id=RUNTIME_TENANT_ID, target_tenant_id=TARGET_TENANT_ID)
    op.execute(
        sa.text(
            """
            WITH moved AS (
                UPDATE contacts c
                SET tenant_id = CAST(:target_tenant_id AS uuid), updated_at = NOW()
                WHERE c.tenant_id = CAST(:runtime_tenant_id AS uuid)
                  AND NOT EXISTS (
                    SELECT 1 FROM contacts existing
                    WHERE existing.tenant_id = CAST(:target_tenant_id AS uuid)
                      AND existing.phone = c.phone
                  )
                RETURNING id
            )
            SELECT COUNT(*) FROM moved
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            WITH moved AS (
                UPDATE conversations c
                SET tenant_id = CAST(:target_tenant_id AS uuid), updated_at = NOW()
                WHERE c.tenant_id = CAST(:runtime_tenant_id AS uuid)
                  AND NOT EXISTS (
                    SELECT 1 FROM conversations existing
                    WHERE existing.tenant_id = CAST(:target_tenant_id AS uuid)
                      AND existing.phone_number = c.phone_number
                  )
                RETURNING id, current_flow
            )
            UPDATE messages m
            SET tenant_id = CAST(:target_tenant_id AS uuid)
            FROM moved
            WHERE m.conversation_id = moved.id
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE messages m
            SET tenant_id = CAST(:target_tenant_id AS uuid)
            FROM conversations c
            WHERE m.conversation_id = c.id
              AND c.tenant_id = CAST(:target_tenant_id AS uuid)
              AND m.tenant_id = CAST(:runtime_tenant_id AS uuid)
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE conversations c
            SET contact_id = target_contact.id
            FROM contacts target_contact
            WHERE c.tenant_id = CAST(:target_tenant_id AS uuid)
              AND target_contact.tenant_id = CAST(:target_tenant_id AS uuid)
              AND target_contact.phone = c.phone_number
              AND (
                c.contact_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM contacts current_contact
                    WHERE current_contact.id = c.contact_id
                      AND current_contact.tenant_id = CAST(:target_tenant_id AS uuid)
                )
              )
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE leads l
            SET tenant_id = CAST(:target_tenant_id AS uuid)
            WHERE l.tenant_id = CAST(:runtime_tenant_id AS uuid)
              AND NOT EXISTS (
                SELECT 1 FROM leads existing
                WHERE existing.tenant_id = CAST(:target_tenant_id AS uuid)
                  AND existing.phone = l.phone
              )
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_sessions fs
            SET tenant_id = CAST(:target_tenant_id AS uuid), updated_at = NOW()
            WHERE fs.tenant_id = CAST(:runtime_tenant_id AS uuid)
              AND EXISTS (
                SELECT 1 FROM conversations c
                WHERE c.tenant_id = CAST(:target_tenant_id AS uuid)
                  AND c.id::text = fs.conversation_id
              )
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_executions fe
            SET tenant_id = CAST(:target_tenant_id AS uuid), updated_at = NOW()
            WHERE fe.tenant_id = CAST(:runtime_tenant_id AS uuid)
              AND EXISTS (
                SELECT 1 FROM conversations c
                WHERE c.tenant_id = CAST(:target_tenant_id AS uuid)
                  AND c.id = fe.conversation_id
              )
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            WITH referenced_flows AS (
                SELECT DISTINCT current_flow AS flow_id
                FROM conversations
                WHERE tenant_id = CAST(:target_tenant_id AS uuid)
                  AND current_flow IS NOT NULL
            )
            UPDATE flows f
            SET tenant_id = CAST(:target_tenant_id AS uuid), updated_at = NOW()
            FROM referenced_flows rf
            WHERE f.id = rf.flow_id
              AND f.tenant_id = CAST(:runtime_tenant_id AS uuid)
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_versions fv
            SET tenant_id = CAST(:target_tenant_id AS uuid)
            FROM flows f
            WHERE fv.flow_id = f.id
              AND f.tenant_id = CAST(:target_tenant_id AS uuid)
              AND fv.tenant_id = CAST(:runtime_tenant_id AS uuid)
            """
        ).bindparams(**params)
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_nodes fn
            SET tenant_id = CAST(:target_tenant_id AS uuid)
            FROM flows f
            WHERE fn.flow_id = f.id
              AND f.tenant_id = CAST(:target_tenant_id AS uuid)
              AND fn.tenant_id = CAST(:runtime_tenant_id AS uuid)
            """
        ).bindparams(**params)
    )


def _deduplicate_remaining_provider_phone_numbers() -> None:
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
                            CASE WHEN id = CAST(:target_provider_id AS uuid) THEN 0 ELSE 1 END,
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
                status = CASE WHEN status = 'active' THEN 'disconnected' ELSE status END,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || jsonb_build_object(
                    'phone_number_id_deduplicated_at', NOW()::text,
                    'previous_phone_number_id', ranked.phone_number_id,
                    'remediation', '20260530_whatsapp_phone_owner'
                ),
                updated_at = NOW()
            FROM ranked
            WHERE p.id = ranked.id
              AND ranked.rn > 1
            """
        ).bindparams(target_provider_id=TARGET_PROVIDER_ID)
    )
