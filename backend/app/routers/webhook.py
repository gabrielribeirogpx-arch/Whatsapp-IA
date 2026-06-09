from datetime import datetime
import asyncio
import os
import logging
import json
from uuid import UUID
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from app.database import get_db
from app.core.redis_client import get_redis_client
from app.models import Conversation, Message, FlowExecution, FlowVersion
from app.schemas.chat import MessageOut
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.conversation_service import get_or_create_conversation
from app.services.lead_auto_service import ensure_whatsapp_lead_for_inbound
from app.services.message_router import handle_incoming_message
from app.services.idempotency_service import register_processed_message
from app.services.tenant_query import enforce_tenant_filter, require_tenant_id
from app.services.message_service import normalize_meta_message
from app.services.realtime_service import publish_dashboard_event, sse_broker
from app.services.flow_service import resolve_flow_for_message
from app.services.flow_runtime_selector import FlowRuntimeSelector, bind_conversation_to_flow, resolve_flow_runtime
from app.services.flow_engine_service import get_active_visual_flow, get_flow_graph, enqueue_flow_send_with_tracking, emit_message_received_event
from app.services.flow_engine import get_node_by_id
from app.services.flow_session_service import FlowSessionService
from app.services.flow_runtime_service import execute_node_chain_until_reply
from app.models.flow import Flow
from app.services.whatsapp_service import send_whatsapp_buttons, send_whatsapp_message_simple
from app.services.intent_service import classify_intent, normalize_input, route_intent
from app.models import Tenant
from app.models.flow_session import FINAL_SESSION_STATUSES, FlowSession
from app.utils.phone import normalize_phone
from app.utils.text import normalize_text
from app.services.queue import enqueue_send_message
from app.services.webhook_ingress import enqueue_webhook_payload
from app.services.tenant_service import resolve_tenant_by_phone_number_id

router = APIRouter()
logger = logging.getLogger(__name__)


def _payload_summary(payload: object, limit: int = 1200) -> str:
    try:
        encoded = json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        encoded = str(payload)
    return encoded[:limit] + ("..." if len(encoded) > limit else "")


def _worker_id() -> str:
    return str(os.getenv("WORKER_ID") or os.getenv("HOSTNAME") or os.getpid())




def _choice_log_context(session: FlowSession | None, selected_row_id: str = "", selected_title: str = "") -> dict[str, object]:
    context = session.context if session and isinstance(getattr(session, "context", None), dict) else {}
    return {
        "session_id": getattr(session, "id", None),
        "node_id": getattr(session, "current_node_id", None) or context.get("choice_node_id"),
        "selected_row_id": selected_row_id or context.get("selected_row_id") or context.get("last_interactive_list_reply_id"),
        "selected_title": selected_title or context.get("selected_title") or context.get("last_interactive_list_reply_title"),
    }


def _log_choice_message_marker(marker: str, session: FlowSession | None, *, selected_row_id: str = "", selected_title: str = "", correlation_id: str = "n/a", reason: str = "n/a") -> None:
    data = _choice_log_context(session, selected_row_id, selected_title)
    logger.info(
        "%s session_id=%s node_id=%s selected_row_id=%s selected_title=%s worker_id=%s correlation_id=%s reason=%s source=webhook",
        marker,
        data.get("session_id"),
        data.get("node_id"),
        data.get("selected_row_id"),
        data.get("selected_title"),
        _worker_id(),
        correlation_id,
        reason,
    )

def _persist_interactive_reply_context(db: Session, session: FlowSession | None, incoming: dict, *, correlation_id: str = "n/a") -> None:
    interactive_type = str(incoming.get("interactive_type") or "").strip()
    selected_row_id = str(incoming.get("selected_row_id") or incoming.get("interactive_reply_id") or "").strip()
    selected_title = str(incoming.get("selected_title") or incoming.get("interactive_reply_title") or "").strip()
    if not session:
        _log_choice_message_marker("[CHOICE RESUME SKIPPED]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="no_active_session")
        _log_choice_message_marker("[CHOICE RESUME REASON]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason=f"interactive_type={interactive_type} selected_row_id_present={bool(selected_row_id)}")
        return
    if interactive_type != "list_reply" or not selected_row_id:
        _log_choice_message_marker("[CHOICE RESUME SKIPPED]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason=f"not_list_reply_or_missing_selected_row_id interactive_type={interactive_type}")
        _log_choice_message_marker("[CHOICE RESUME REASON]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason=f"selected_row_id_present={bool(selected_row_id)}")
        return
    _log_choice_message_marker("[CHOICE MESSAGE RECEIVED]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="persist_interactive_reply_context")
    if isinstance(getattr(session, "context", None), dict) and session.context.get("waiting_choice") is True:
        _log_choice_message_marker("[CHOICE WAITING SESSION FOUND]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="waiting_choice_true")
    else:
        _log_choice_message_marker("[CHOICE RESUME SKIPPED]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="active_session_not_waiting_choice")
        _log_choice_message_marker("[CHOICE RESUME REASON]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason=f"waiting_choice={((session.context or {}).get('waiting_choice') if isinstance(getattr(session, 'context', None), dict) else None)}")
    session.context = {
        **(session.context or {}),
        "last_interactive_type": interactive_type,
        "last_interactive_list_reply_id": selected_row_id,
        "last_interactive_list_reply_title": selected_title,
        "selected_row_id": selected_row_id,
        "selected_title": selected_title,
        "correlation_id": correlation_id,
        "last_interactive_message_id": correlation_id,
    }
    db.add(session)
    logger.info(
        "[CHOICE LIST RESPONSE] session_id=%s current_node_id=%s choice_node_id=%s selected_row_id=%s target_node_id=%s worker_id=%s correlation_id=%s source=webhook selected_title=%s",
        session.id,
        getattr(session, "current_node_id", None),
        (session.context or {}).get("choice_node_id") if isinstance(session.context, dict) else None,
        selected_row_id,
        (session.context or {}).get("selected_choice_target_node_id") if isinstance(session.context, dict) else None,
        _worker_id(),
        correlation_id,
        selected_title,
    )



async def _process_runtime_events(
    *,
    events: list[dict],
    phone: str,
    execution: FlowExecution | None,
    tenant_uuid: UUID,
    wa_id: str,
    db: Session,
) -> bool:
    for event in events:
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "delay":
            seconds = float(event.get("seconds") or 0)
            logger.info("[FLOW DELAY EVENT] tenant_id=%s wa_id=%s seconds=%s", tenant_uuid, wa_id, seconds)
            if seconds <= 5:
                await asyncio.sleep(seconds)
                continue

            if execution is not None:
                runtime_state = execution.state if isinstance(execution.state, dict) else {}
                runtime_state["pending_delay"] = True
                runtime_state["pending_delay_at"] = datetime.utcnow().isoformat()
                runtime_state["pending_delay_seconds"] = seconds
                runtime_state["pending_delay_tenant_id"] = str(tenant_uuid)
                runtime_state["pending_delay_wa_id"] = wa_id
                runtime_state["pending_delay_next_node_id"] = execution.current_node_id
                runtime_state["pending_delay_resume_at"] = datetime.utcnow().isoformat()
                execution.state = runtime_state
                db.add(execution)
                db.commit()
                logger.info("[FLOW SESSION SAVED] execution_id=%s tenant_id=%s wa_id=%s", execution.id, tenant_uuid, wa_id)
            return True

        if event_type in {"send_message", "send_list"}:
            text = str(event.get("text") or event.get("body_text") or "").strip()
            if not text:
                continue
            logger.info("[FLOW SEND EVENT] tenant_id=%s wa_id=%s event_type=%s", tenant_uuid, wa_id, event_type)
            if event.get("after_delay") is True:
                logger.info("[FLOW SEND AFTER DELAY] tenant_id=%s wa_id=%s", tenant_uuid, wa_id)
            if db is None:
                if event_type == "send_message":
                    send_whatsapp_message_simple(phone, text)
                    continue
                enqueue_send_message({
                    "tenant_id": tenant_uuid,
                    "phone": phone,
                    "text": text,
                    "interactive_type": "list",
                    "sections": event.get("sections") if isinstance(event.get("sections"), list) else [],
                    "options": event.get("options") if isinstance(event.get("options"), list) else [],
                    "node_type": str(event.get("node_type") or "choice"),
                    "node_id": str(event.get("node_id") or "") or None,
                    "flow_engine": str(event.get("flow_engine") or "new"),
                    "flow_executor": str(event.get("flow_executor") or "execute_node_chain_until_reply"),
                    "flow_send_source": "webhook:_process_runtime_events:send_list",
                })
                continue

            flow_id = None
            flow_version_id = None
            node_id = None
            if execution is not None:
                flow_version_id = execution.flow_version_id
                node_id = event.get("node_id") or execution.current_node_id
                flow_version = db.get(FlowVersion, execution.flow_version_id)
                flow_id = flow_version.flow_id if flow_version else None
            conversation = (
                db.query(Conversation)
                .filter(Conversation.tenant_id == tenant_uuid, Conversation.phone_number == normalize_phone(phone))
                .order_by(Conversation.updated_at.desc())
                .first()
            )

            if event_type == "send_list":
                sections = event.get("sections") if isinstance(event.get("sections"), list) else []
                options = event.get("options") if isinstance(event.get("options"), list) else []
                payload = {
                    "tenant_id": tenant_uuid,
                    "phone": phone,
                    "text": text,
                    "interactive_type": "list",
                    "sections": sections,
                    "options": options,
                    "flow_id": str(flow_id) if flow_id else None,
                    "flow_version_id": str(flow_version_id) if flow_version_id else None,
                    "session_id": str(conversation.id) if conversation else None,
                    "node_id": str(node_id) if node_id else None,
                    "node_type": str(event.get("node_type") or "choice"),
                    "conversation_id": str(conversation.id) if conversation else None,
                    "flow_engine": str(event.get("flow_engine") or "new"),
                    "flow_executor": str(event.get("flow_executor") or "execute_node_chain_until_reply"),
                    "flow_send_source": "webhook:_process_runtime_events:send_list",
                }
                job_id = enqueue_send_message(payload)
                logger.info(
                    "[CHOICE LIST ENQUEUED] session_id=%s node_id=%s flow_id=%s interactive_type=%s job_id=%s options_count=%s payload_summary=%s",
                    payload.get("session_id"),
                    payload.get("node_id"),
                    payload.get("flow_id"),
                    payload.get("interactive_type"),
                    job_id,
                    len(options),
                    _payload_summary({"text": text, "sections": sections, "options": options}),
                )
                continue

            enqueue_flow_send_with_tracking(
                db=db,
                tenant_id=tenant_uuid,
                phone=phone,
                text=text,
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                conversation_id=conversation.id if conversation else None,
                node_id=node_id,
                channel="whatsapp",
                buttons=event.get("buttons") if isinstance(event.get("buttons", []), list) else None,
                template_or_node_text=str(event.get("template_name") or event.get("node_label") or ""),
                flow_engine=str(event.get("flow_engine") or "new"),
                flow_executor=str(event.get("flow_executor") or "execute_node_chain_until_reply"),
                flow_send_source="webhook:_process_runtime_events:send_message",
            )

    return False


def _clear_pending_delay_state(execution: FlowExecution) -> None:
    runtime_state = execution.state if isinstance(execution.state, dict) else {}
    runtime_state["pending_delay"] = False
    runtime_state.pop("pending_delay_next_node_id", None)
    runtime_state.pop("pending_delay_at", None)
    runtime_state.pop("pending_delay_seconds", None)
    runtime_state.pop("pending_delay_tenant_id", None)
    runtime_state.pop("pending_delay_wa_id", None)
    runtime_state.pop("pending_delay_resume_at", None)
    execution.state = runtime_state

def _find_start_node(nodes: list[dict]) -> dict | None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(node.get("type") or "").lower()
        if (
            data.get("isStart") is True
            or data.get("is_start") is True
            or node.get("isStart") is True
            or node.get("is_start") is True
            or node_type == "start"
            or str(node.get("id") or "").lower() == "start"
        ):
            return node
    return None


def _find_next_node_id(source_node_id: str | None, edges: list[dict]) -> str | None:
    if not source_node_id:
        return None
    edge = next((e for e in edges if str(e.get("source")) == str(source_node_id)), None)
    if not edge:
        return None
    target = edge.get("target")
    return str(target) if target else None


def _has_outgoing_edges(node_id: str | None, edges: list[dict]) -> bool:
    if not node_id:
        return False
    return any(str(edge.get("source")) == str(node_id) for edge in edges)

def _looks_like_name(text: str) -> bool:
    if not text:
        return False

    cleaned = text.strip()
    if not cleaned or len(cleaned) > 40:
        return False

    if any(char.isdigit() for char in cleaned):
        return False

    words = cleaned.split()
    return len(words) <= 4


def _resolve_request_tenant_id(request: Request) -> uuid.UUID | None:
    tenant_from_middleware = getattr(request.state, "tenant_id", None)
    if tenant_from_middleware:
        return tenant_from_middleware

    tenant_header = (request.headers.get("x-tenant-id") or "").strip()
    if not tenant_header:
        return None
    try:
        return uuid.UUID(tenant_header)
    except ValueError:
        return None


async def _parse_webhook_payload(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Webhook rejeitado: payload JSON inválido")
        return {}

    if not isinstance(payload, dict):
        logger.warning("Webhook rejeitado: payload não é objeto")
        return {}
    return payload


async def _process_meta_webhook(request: Request, db: Session) -> dict[str, str]:
    payload = await _parse_webhook_payload(request)
    if not payload:
        return {"status": "ignored"}

    logger.info("event=meta_webhook_received keys=%s", list(payload.keys()))
    logger.info("[WEBHOOK RAW] payload=%s", str(payload)[:800])
    messages_data = normalize_meta_message(payload)

    if not messages_data:
        logger.info("Evento ignorado: payload sem mensagens processáveis")
        return {"status": "ignored"}

    processed_any = False

    for incoming in messages_data:
        try:
            phone = incoming["phone"]
            normalized_phone = normalize_phone(phone)
            incoming_message = incoming.get("text") or ""
            incoming_type = incoming.get("type") or "unknown"
            logger.info("[WEBHOOK DEBUG] type=%s message=%s", incoming_type, incoming_message)
            contact_name = incoming.get("name")
            phone_number_id = incoming.get("phone_number_id")
            logger.info(
                "Mensagem normalizada recebida phone=%s type=%s phone_number_id=%s",
                normalized_phone,
                incoming_type,
                phone_number_id,
            )

            tenant = resolve_tenant_by_phone_number_id(db, phone_number_id)
            if not tenant:
                logger.warning(
                    "[WEBHOOK ERROR] tenant_not_found phone_number_id=%s phone=%s",
                    phone_number_id,
                    normalized_phone,
                )
                continue

            tenant_id = tenant.id
            incoming["tenant_id"] = str(tenant_id)
            logger.info("[TENANT RESOLVED] tenant_id=%s slug=%s phone_number_id=%s", tenant.id, tenant.slug, phone_number_id)
            logger.info(
                "[WEBHOOK TENANT RESOLVED]\ntenant_id=%s\nphone_number_id=%s",
                tenant.id,
                phone_number_id,
            )
            message_id = (incoming.get("message_id") or "").strip()
            was_inserted = register_processed_message(db=db, tenant_id=tenant_id, message_id=message_id)
            if not was_inserted:
                logger.info("Mensagem duplicada ignorada tenant_id=%s phone=%s message_id=%s", tenant_id, normalized_phone, message_id)
                continue

            if incoming_type not in {"text", "interactive"} or not incoming_message:
                logger.info("Evento ignorado: tipo=%s sem texto processável", incoming_type)
                continue

            processed_any = True
            contact = upsert_contact_for_phone(
                db,
                tenant_id=tenant_id,
                phone=normalized_phone,
                name=contact_name,
            )

            conversation = (
                db.query(Conversation)
                .filter(
                    Conversation.tenant_id == tenant.id,
                    Conversation.phone_number == normalized_phone
                )
                .order_by(Conversation.updated_at.desc())
                .first()
            )
            existed = conversation is not None

            if not conversation:
                conversation, existed = get_or_create_conversation(
                    db=db,
                    tenant_id=tenant_id,
                    phone=normalized_phone,
                    contact_id=contact.id if contact else None,
                )

            if existed:
                logger.info("Conversa encontrada id=%s", conversation.id)
            else:
                logger.info("Nenhuma conversa encontrada, criando nova para %s", normalized_phone)

            if contact_name:
                conversation.name = contact_name
                if contact:
                    contact.name = contact_name
                logger.info(
                    "[CONTACT PROFILE NAME SAVED] phone=%s name=%s",
                    normalized_phone,
                    contact_name,
                )
            ensure_conversation_contact_link(conversation, contact)
            lead_result = ensure_whatsapp_lead_for_inbound(
                db=db,
                tenant_id=tenant_id,
                phone=normalized_phone,
                contact=contact,
                conversation=conversation,
                name=contact_name or conversation.name,
                message_text=incoming_message,
                conversation_created=not existed,
            )

            if conversation.name is None and _looks_like_name(incoming_message):
                conversation.name = incoming_message.strip()
            if contact and conversation.name and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
            if contact:
                contact.last_message_at = datetime.utcnow()

            logger.info("Salvando mensagem de entrada phone=%s conversation_id=%s", normalized_phone, conversation.id)
            inbound_message = Message(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                text=incoming_message,
                from_me=False,
                created_at=datetime.utcnow(),
            )
            db.add(inbound_message)
            db.commit()
            db.refresh(inbound_message)
            message_payload = {
                "event": "message",
                "message": MessageOut.model_validate(inbound_message).model_dump(mode="json"),
            }
            print("[WS BROADCAST] message", conversation.id)
            await sse_broker.publish(f"{tenant.id}:{normalized_phone}", message_payload)
            await sse_broker.publish(f"{tenant.id}:{conversation.id}", message_payload)

            display_name = (contact_name or conversation.name or normalized_phone or "Contato").strip()
            if lead_result and lead_result.created:
                await publish_dashboard_event(
                    tenant_id=tenant.id,
                    payload={
                        "event": "dashboard_activity",
                        "refresh": ["analytics", "activity", "conversations"],
                        "activity": {
                            "id": str(lead_result.lead.id),
                            "type": "LEAD_CREATED",
                            "title": f"Novo lead criado: {display_name}",
                            "description": normalized_phone,
                            "entity_type": "lead",
                            "entity_id": str(lead_result.lead.id),
                            "contact_name": contact_name or conversation.name,
                            "phone": normalized_phone,
                            "created_at": datetime.utcnow().isoformat(),
                        },
                    },
                )
            else:
                await publish_dashboard_event(
                    tenant_id=tenant.id,
                    payload={
                        "event": "dashboard_activity",
                        "refresh": ["analytics", "conversations"],
                        "activity": {
                            "id": str(inbound_message.id),
                            "type": "MESSAGE_RECEIVED",
                            "title": display_name,
                            "description": incoming_message,
                            "entity_type": "conversation",
                            "entity_id": str(conversation.id),
                            "contact_name": contact_name or conversation.name,
                            "phone": normalized_phone,
                            "created_at": inbound_message.created_at.isoformat(),
                        },
                    },
                )

            should_resolve_flow = conversation.mode != "flow" and (
                conversation.current_flow_id is None or conversation.current_node_id is None
            )
            selected_flow = None
            selected_flow_reason = None
            if conversation.current_flow_id:
                selected_flow = (
                    db.execute(
                        select(Flow).where(
                            Flow.id == conversation.current_flow_id,
                            Flow.tenant_id == conversation.tenant_id,
                            Flow.is_active.is_(True),
                            Flow.is_deleted.is_(False),
                            Flow.deleted_at.is_(None),
                        )
                    )
                    .scalars()
                    .first()
                )
                if selected_flow:
                    selected_flow_reason = "conversation_current_active_flow"
                else:
                    logger.warning(
                        "[V2 STALE CONVERSATION FLOW] tenant_id=%s conversation_id=%s stale_flow_id=%s reason=current_flow_not_active",
                        conversation.tenant_id,
                        conversation.id,
                        conversation.current_flow_id,
                    )
            active_builder_flow = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
            if active_builder_flow and (selected_flow is None or selected_flow.id != active_builder_flow.id):
                logger.warning(
                    "[V2 FLOW ACTIVE MISMATCH] tenant_id=%s conversation_id=%s conversation_flow_id=%s active_flow_id=%s active_flow_version_id=%s reason=builder_active_overrides_stale_conversation_flow",
                    conversation.tenant_id,
                    conversation.id,
                    getattr(selected_flow, "id", None) or conversation.current_flow_id,
                    active_builder_flow.id,
                    active_builder_flow.published_version_id,
                )
                selected_flow = active_builder_flow
                selected_flow_reason = "builder_active_overrides_stale_conversation_flow"
                bind_conversation_to_flow(db, conversation=conversation, flow=active_builder_flow)
            if should_resolve_flow and selected_flow is None:
                resolved_flow = resolve_flow_for_message(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    message_text=incoming_message,
                    conversation=conversation,
                )
                if resolved_flow:
                    selected_flow = resolved_flow
                    selected_flow_reason = "message_trigger_resolved_flow"
                    bind_conversation_to_flow(db, conversation=conversation, flow=resolved_flow)
                else:
                    logger.info("[FALLBACK ROUTING] tenant=%s conversation=%s", conversation.tenant_id, conversation.id)

            if selected_flow:
                selected_runtime = resolve_flow_runtime(selected_flow)
                logger.info(
                    "[FLOW SELECTED]\nflow_id=%s\nruntime=%s\npublished_version_id=%s",
                    selected_flow.id,
                    selected_runtime,
                    selected_flow.published_version_id,
                )
            if selected_flow and resolve_flow_runtime(selected_flow) == "v2":
                if incoming_type == "interactive":
                    logger.info(
                        "[CHOICE WEBHOOK RECEIVED] source=webhook_router flow_id=%s conversation_id=%s message_id=%s interactive_type=%s interactive_reply_id=%s interactive_reply_title=%s selected_row_id=%s selected_title=%s text=%s",
                        selected_flow.id,
                        conversation.id,
                        message_id,
                        incoming.get("interactive_type"),
                        incoming.get("interactive_reply_id"),
                        incoming.get("interactive_reply_title"),
                        incoming.get("selected_row_id"),
                        incoming.get("selected_title"),
                        incoming_message,
                    )
                FlowRuntimeSelector().dispatch(
                    db=db,
                    flow=selected_flow,
                    tenant_id=conversation.tenant_id,
                    phone=normalized_phone,
                    message_text=incoming_message,
                    conversation=conversation,
                    contact_id=contact.id if contact else None,
                    input_message_id=message_id,
                    metadata={
                        "source": "webhook",
                        "message_type": incoming_type,
                        "phone_number_id": phone_number_id,
                        "interactive_type": incoming.get("interactive_type"),
                        "interactive_reply_id": incoming.get("interactive_reply_id"),
                        "interactive_reply_title": incoming.get("interactive_reply_title"),
                        "selected_row_id": incoming.get("selected_row_id") or incoming.get("interactive_reply_id"),
                        "selected_title": incoming.get("selected_title") or incoming.get("interactive_reply_title"),
                        "selected_flow_reason": selected_flow_reason or "webhook_selected_flow",
                    },
                )
                logger.info(
                    "[FLOW RUNTIME SELECTOR] skipped_v1=true runtime=v2 tenant_id=%s flow_id=%s conversation_id=%s",
                    conversation.tenant_id,
                    selected_flow.id,
                    conversation.id,
                )
                continue

            active_session = (
                db.query(FlowSession)
                .filter(
                    FlowSession.tenant_id == conversation.tenant_id,
                    FlowSession.conversation_id == str(conversation.id),
                )
                .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
                .first()
            )
            selected_row_id = str(incoming.get("selected_row_id") or incoming.get("interactive_reply_id") or "").strip()
            selected_title = str(incoming.get("selected_title") or incoming.get("interactive_reply_title") or "").strip()
            incoming_correlation_id = str(incoming.get("message_id") or incoming.get("correlation_id") or "n/a")
            if incoming_type == "interactive" and str(incoming.get("interactive_type") or "").strip() == "list_reply":
                _log_choice_message_marker("[CHOICE MESSAGE RECEIVED]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=incoming_correlation_id, reason="webhook_before_context_persist")
            if (
                active_session
                and (active_session.status or "").lower() not in FINAL_SESSION_STATUSES
            ):
                if isinstance(getattr(active_session, "context", None), dict) and active_session.context.get("waiting_choice") is True:
                    _log_choice_message_marker("[CHOICE WAITING SESSION FOUND]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=incoming_correlation_id, reason="active_session_before_context_persist")
                _persist_interactive_reply_context(db, active_session, incoming, correlation_id=incoming_correlation_id)
                emit_message_received_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=active_session.flow_id,
                    flow_version_id=None,
                    node_id=conversation.current_node_id,
                    message_text=incoming_message,
                    source="webhook_active_session",
                    input_kind=incoming_type,
                    dedupe_bucket_seconds=3,
                )

            handle_incoming_message(db, inbound_message, conversation)

            logger.info("Evento processado telefone=%s conteúdo=%s", normalized_phone, incoming_message)
        except Exception as exc:
            db.rollback()
            print("[FLOW EXECUTION ERROR]", exc)
            logger.exception(
                "[WEBHOOK ERROR] failed to process message_id=%s phone=%s error=%s",
                incoming.get("message_id"),
                incoming.get("phone"),
                str(exc),
            )
            try:
                if incoming.get("phone"):
                    enqueue_send_message({
                        "tenant_id": tenant_id,
                        "phone": normalize_phone(incoming["phone"]),
                        "text": "Tive um problema aqui 😅 mas já estou corrigindo. Pode tentar de novo?",
                    })
                    logger.warning("[WEBHOOK FALLBACK TRIGGERED] phone=%s", incoming.get("phone"))
            except Exception:
                logger.exception("Falha ao enviar fallback do webhook")
            continue

    db.commit()
    return {"status": "message processed" if processed_any else "ignored"}


@router.get("/webhook")
async def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="hub.mode inválido")

    tenant = None
    if hub_verify_token:
        tenant = db.execute(select(Tenant).where(Tenant.verify_token == hub_verify_token)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=403, detail="verify_token ausente")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    # Endpoint canônico de entrada Meta: ACK imediato + enqueue no worker.
    # Mantemos esse endpoint sem prefixo porque já é usado por integrações atuais.
    await enqueue_webhook_payload(request)
    return {"status": "received"}


@router.post("/webhook/meta")
async def webhook_meta(request: Request, db: Session = Depends(get_db)):
    try:
        return await _process_meta_webhook(request=request, db=db)
    except Exception as e:
        db.rollback()
        logger.exception("Erro ao processar /webhook/meta: %s", str(e))
        return {"status": "ignored"}


@router.get("/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db)):
    tenant_id = require_tenant_id(_resolve_request_tenant_id(request), context="list_conversations")
    query = (
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.phone_number, Conversation.created_at, Conversation.tenant_id))
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
        .limit(200)
    )
    query = enforce_tenant_filter(query, Conversation, tenant_id, context="list_conversations")

    conversations = db.execute(query).scalars().all()

    response: list[dict[str, str | None]] = []
    for conversation in conversations:
        last_message = db.execute(
            enforce_tenant_filter(
                select(Message).where(Message.conversation_id == conversation.id),
                Message,
                tenant_id,
                context="list_conversations_last_message",
            )
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(1)
        ).scalars().first()
        response.append(
            {
                "id": str(conversation.id),
                "phone_number": conversation.phone_number,
                "last_message": (last_message.text if last_message else None),
            }
        )
    return response


@router.get("/messages/{conversation_id}")
def list_messages(conversation_id: UUID, request: Request, db: Session = Depends(get_db)):
    tenant_id = require_tenant_id(_resolve_request_tenant_id(request), context="list_messages")
    query = enforce_tenant_filter(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(500),
        Message,
        tenant_id,
        context="list_messages",
    )
    messages = db.execute(query).scalars().all()

    return [
        {
            "id": str(item.id),
            "conversation_id": str(item.conversation_id),
            "from_me": item.from_me,
            "text": item.text,
            "created_at": item.created_at.isoformat(),
        }
        for item in messages
    ]
