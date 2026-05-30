from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin-investigation"])

TARGET_CONVERSATION_ID = "b51fef94-1be8-456e-93a9-69ca4a8ea18c"
TARGET_FLOW_ID = "50f7b54f-2ccd-4203-bb82-f946f4a9f078"
TARGET_LEAD_ID = "8de6a070-1290-494f-b274-cb6de8660e69"
TARGET_PHONE_NUMBER_ID = "876969468828520"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _rows(db: Session, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = db.execute(text(statement), params or {})
    return [
        {str(key): _jsonable(value) for key, value in row.items()}
        for row in result.mappings().all()
    ]


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


@router.post("/multi-tenant-investigation")
def multi_tenant_investigation(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Temporary read-only multi-tenant diagnostic endpoint.

    This endpoint intentionally only executes SELECT statements and does not expose
    WhatsApp tokens or any other encrypted secret columns.
    """

    params = {
        "conversation_id": TARGET_CONVERSATION_ID,
        "flow_id": TARGET_FLOW_ID,
        "lead_id": TARGET_LEAD_ID,
        "phone_number_id": TARGET_PHONE_NUMBER_ID,
    }

    tenants = _rows(
        db,
        """
        SELECT
            id,
            name,
            slug,
            phone_number_id,
            webhook_url,
            webhook_status,
            language,
            plan,
            max_monthly_messages,
            usage_month,
            messages_used_month,
            is_blocked,
            ai_mode,
            workspace_profile
        FROM tenants
        ORDER BY name, id
        """,
    )

    providers_meta = _rows(
        db,
        """
        SELECT
            id AS provider_id,
            tenant_id,
            COALESCE(display_name, provider_type) AS provider_name,
            provider_type,
            phone_number_id,
            waba_id,
            business_id,
            is_active,
            status,
            last_connection_check_at,
            created_at,
            updated_at
        FROM tenant_whatsapp_providers
        WHERE provider_type = 'meta_cloud'
        ORDER BY tenant_id, is_active DESC, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        """,
    )

    conversation = _first(
        _rows(
            db,
            """
            SELECT
                c.id,
                c.tenant_id,
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                c.contact_id,
                c.phone_number,
                c.name,
                c.mode,
                c.conversation_state,
                c.current_flow AS current_flow_id,
                c.current_step,
                c.current_node_id,
                c.context,
                c.last_input,
                c.retries,
                c.last_bot_question,
                c.current_objective,
                c.last_bot_triggered_message_id,
                c.last_intent,
                c.intent_history,
                c.last_intent_at,
                c.lead_score,
                c.created_at,
                c.updated_at
            FROM conversations c
            LEFT JOIN tenants t ON t.id = c.tenant_id
            WHERE c.id = CAST(:conversation_id AS uuid)
            """,
            params,
        )
    )

    flow = _first(
        _rows(
            db,
            """
            SELECT
                f.id,
                f.tenant_id,
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                f.name,
                f.description,
                f.is_active,
                f.is_deleted,
                f.trigger_type,
                f.trigger_value,
                f.keywords,
                f.stop_words,
                f.priority,
                f.version,
                f.status,
                f.current_version_id,
                f.published_version_id,
                f.created_at,
                f.updated_at,
                f.deleted_at
            FROM flows f
            LEFT JOIN tenants t ON t.id = f.tenant_id
            WHERE f.id = CAST(:flow_id AS uuid)
            """,
            params,
        )
    )

    lead = _first(
        _rows(
            db,
            """
            SELECT
                l.id,
                l.tenant_id,
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                l.phone,
                l.name,
                l.stage,
                l.stage_id,
                l.temperature,
                l.score,
                l.email,
                l.source,
                l.status,
                l.owner_id,
                l.contact_id,
                l.conversation_id,
                l.last_interaction,
                l.last_contact_at,
                l.entered_stage_at,
                l.created_at,
                l.updated_at
            FROM leads l
            LEFT JOIN tenants t ON t.id = l.tenant_id
            WHERE l.id = CAST(:lead_id AS uuid)
            """,
            params,
        )
    )

    conversation_messages = _rows(
        db,
        """
        SELECT id, tenant_id, conversation_id, from_me, created_at, LEFT(text, 500) AS text_preview
        FROM messages
        WHERE conversation_id = CAST(:conversation_id AS uuid)
        ORDER BY created_at DESC, id
        """,
        params,
    )

    flow_records = {
        "versions": _rows(
            db,
            """
            SELECT id, flow_id, tenant_id, version, graph_checksum, start_node_id, start_text_preview,
                   created_from_source, is_active, is_published, created_at
            FROM flow_versions
            WHERE flow_id = CAST(:flow_id AS uuid)
            ORDER BY version DESC, created_at DESC NULLS LAST
            """,
            params,
        ),
        "nodes": _rows(
            db,
            """
            SELECT id, flow_id, tenant_id, type, content, metadata, is_terminal, position_x, position_y, created_at
            FROM flow_nodes
            WHERE flow_id = CAST(:flow_id AS uuid)
            ORDER BY created_at, id
            """,
            params,
        ),
        "edges": _rows(
            db,
            """
            SELECT id, flow_id, source, target, condition
            FROM flow_edges
            WHERE flow_id = CAST(:flow_id AS uuid)
            ORDER BY id
            """,
            params,
        ),
        "sessions": _rows(
            db,
            """
            SELECT id, tenant_id, flow_id, flow_version_id, conversation_id, user_identifier, current_node_id,
                   status, context, variables, created_at, updated_at
            FROM flow_sessions
            WHERE flow_id = CAST(:flow_id AS uuid)
               OR conversation_id = :conversation_id
            ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
            """,
            params,
        ),
        "executions": _rows(
            db,
            """
            SELECT id, tenant_id, flow_id, contact_id, conversation_id, flow_version_id, user_phone,
                   started_at, completed_at, status, current_node, completed, current_node_id, state, updated_at
            FROM flow_executions
            WHERE flow_id = CAST(:flow_id AS uuid)
               OR conversation_id = CAST(:conversation_id AS uuid)
            ORDER BY updated_at DESC NULLS LAST, started_at DESC NULLS LAST
            """,
            params,
        ),
    }

    lead_records = {
        "linked_contact": _rows(
            db,
            """
            SELECT c.id, c.tenant_id, c.phone, c.name, c.stage, c.score, c.first_name, c.last_name,
                   c.email, c.tags_json, c.source, c.opt_in_status, c.last_interaction_at,
                   c.lifecycle_stage, c.created_at, c.updated_at
            FROM contacts c
            JOIN leads l ON l.contact_id = c.id
            WHERE l.id = CAST(:lead_id AS uuid)
            """,
            params,
        ),
        "linked_conversation": _rows(
            db,
            """
            SELECT c.id, c.tenant_id, c.contact_id, c.phone_number, c.name, c.mode, c.current_flow AS current_flow_id,
                   c.current_node_id, c.created_at, c.updated_at
            FROM conversations c
            JOIN leads l ON l.conversation_id = c.id
            WHERE l.id = CAST(:lead_id AS uuid)
            """,
            params,
        ),
    }

    phone_number_associations = {
        "tenants": _rows(
            db,
            """
            SELECT id, name, slug, phone_number_id, webhook_status, plan, is_blocked
            FROM tenants
            WHERE phone_number_id = :phone_number_id
            ORDER BY name, id
            """,
            params,
        ),
        "providers_meta": _rows(
            db,
            """
            SELECT
                id AS provider_id,
                tenant_id,
                COALESCE(display_name, provider_type) AS provider_name,
                provider_type,
                phone_number_id,
                waba_id,
                business_id,
                is_active,
                status,
                created_at,
                updated_at
            FROM tenant_whatsapp_providers
            WHERE provider_type = 'meta_cloud' AND phone_number_id = :phone_number_id
            ORDER BY is_active DESC, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
            """,
            params,
        ),
    }

    duplicate_phone_number_ids = _rows(
        db,
        """
        SELECT
            phone_number_id,
            COUNT(*) AS provider_count,
            COUNT(DISTINCT tenant_id) AS tenant_count,
            ARRAY_AGG(DISTINCT tenant_id::text ORDER BY tenant_id::text) AS tenant_ids,
            ARRAY_AGG(id::text ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST) AS provider_ids
        FROM tenant_whatsapp_providers
        WHERE phone_number_id IS NOT NULL AND BTRIM(phone_number_id) <> ''
        GROUP BY phone_number_id
        HAVING COUNT(DISTINCT tenant_id) > 1
        ORDER BY tenant_count DESC, provider_count DESC, phone_number_id
        """,
    )

    target_phone_duplicate = _first(
        [
            item
            for item in duplicate_phone_number_ids
            if item.get("phone_number_id") == TARGET_PHONE_NUMBER_ID
        ]
    )

    runtime_tenant_id = conversation.get("tenant_id") if conversation else None
    runtime_provider_rows = []
    if runtime_tenant_id:
        runtime_provider_rows = _rows(
            db,
            """
            SELECT
                id AS provider_id,
                tenant_id,
                COALESCE(display_name, provider_type) AS provider_name,
                provider_type,
                phone_number_id,
                waba_id,
                business_id,
                is_active,
                status,
                created_at,
                updated_at,
                'resolve_active_meta_provider_credentials: provider meta_cloud ativo do tenant da conversa, ordenado por updated_at desc' AS criterio
            FROM tenant_whatsapp_providers
            WHERE tenant_id = CAST(:runtime_tenant_id AS uuid)
              AND provider_type = 'meta_cloud'
            ORDER BY is_active DESC, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
            LIMIT 1
            """,
            {"runtime_tenant_id": runtime_tenant_id},
        )

    provider_usado_runtime = _first(runtime_provider_rows)
    provider_configurado_manual = _first(phone_number_associations["providers_meta"])

    correct_tenant_id = (
        provider_configurado_manual.get("tenant_id")
        if provider_configurado_manual
        else (phone_number_associations["tenants"][0].get("id") if phone_number_associations["tenants"] else None)
    )
    tenant_correto = _first(
        [tenant for tenant in tenants if str(tenant.get("id")) == str(correct_tenant_id)]
    ) if correct_tenant_id else None

    incorrect_tenant_ids = set()
    for source in (conversation, flow, lead, provider_usado_runtime):
        if source and source.get("tenant_id") and str(source.get("tenant_id")) != str(correct_tenant_id):
            incorrect_tenant_ids.add(str(source.get("tenant_id")))
    for provider in phone_number_associations["providers_meta"][1:]:
        if provider.get("tenant_id") and str(provider.get("tenant_id")) != str(correct_tenant_id):
            incorrect_tenant_ids.add(str(provider.get("tenant_id")))

    tenants_incorretos = [
        tenant for tenant in tenants if str(tenant.get("id")) in incorrect_tenant_ids
    ]

    associated_tenant_ids = sorted(
        {
            str(value)
            for value in [
                *(item.get("id") for item in phone_number_associations["tenants"]),
                *(item.get("tenant_id") for item in phone_number_associations["providers_meta"]),
                runtime_tenant_id,
                flow.get("tenant_id") if flow else None,
                lead.get("tenant_id") if lead else None,
            ]
            if value
        }
    )

    scoped_records = {}
    if associated_tenant_ids:
        scoped_params = {"tenant_ids": associated_tenant_ids, **params}
        scoped_records = {
            "conversations_for_associated_tenants": _rows(
                db,
                """
                SELECT id, tenant_id, phone_number, name, current_flow AS current_flow_id, current_node_id, created_at, updated_at
                FROM conversations
                WHERE tenant_id::text = ANY(:tenant_ids)
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 200
                """,
                scoped_params,
            ),
            "flows_for_associated_tenants": _rows(
                db,
                """
                SELECT id, tenant_id, name, status, is_active, is_deleted, trigger_type, trigger_value, current_version_id, published_version_id, created_at, updated_at
                FROM flows
                WHERE tenant_id::text = ANY(:tenant_ids)
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 200
                """,
                scoped_params,
            ),
            "leads_for_associated_tenants": _rows(
                db,
                """
                SELECT id, tenant_id, phone, name, stage, status, conversation_id, contact_id, created_at, updated_at
                FROM leads
                WHERE tenant_id::text = ANY(:tenant_ids)
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT 200
                """,
                scoped_params,
            ),
        }

    return {
        "readonly": True,
        "endpoint_status": "temporary_investigation_endpoint",
        "params": {
            "conversation_id": TARGET_CONVERSATION_ID,
            "flow_id": TARGET_FLOW_ID,
            "lead_id": TARGET_LEAD_ID,
            "phone_number_id": TARGET_PHONE_NUMBER_ID,
        },
        "tenants": tenants,
        "providers_meta": providers_meta,
        "conversation": conversation,
        "flow": flow,
        "flow_records": flow_records,
        "lead": lead,
        "lead_records": lead_records,
        "conversation_messages": conversation_messages,
        "phone_number_id_associations": phone_number_associations,
        "records_associated_to_phone_number_id": scoped_records,
        "duplicate_phone_number_ids": duplicate_phone_number_ids,
        "target_phone_number_id_duplicate": target_phone_duplicate,
        "tenant_correto": tenant_correto,
        "tenant_incorreto": tenants_incorretos[0] if tenants_incorretos else None,
        "tenants_incorretos": tenants_incorretos,
        "provider_usado_runtime": provider_usado_runtime,
        "provider_configurado_manual": provider_configurado_manual,
        "diagnostic_notes": [
            "provider_usado_runtime simula a resolução do send_worker: tenant_id da conversa + provider_type=meta_cloud + is_active desc + updated_at desc.",
            "provider_configurado_manual é o provider Meta com phone_number_id alvo, priorizando ativo e atualização mais recente.",
            "Nenhuma coluna de token/secret é selecionada neste endpoint.",
        ],
    }
