from datetime import datetime
import asyncio
import logging
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
from app.services.message_router import handle_incoming_message
from app.services.idempotency_service import register_processed_message
from app.services.tenant_query import enforce_tenant_filter, require_tenant_id
from app.services.message_service import normalize_meta_message
from app.services.realtime_service import sse_broker
from app.services.flow_service import resolve_flow_for_message
from app.services.flow_engine_service import get_flow_graph, enqueue_flow_send_with_tracking
from app.services.flow_engine import get_node_by_id
from app.services.flow_session_service import FlowSessionService
from app.services.flow_runtime_service import execute_node_chain_until_reply
from app.models.flow import Flow
from app.services.whatsapp_service import send_whatsapp_buttons
from app.services.intent_service import classify_intent, normalize_input, route_intent
from app.models import Tenant
from app.utils.phone import normalize_phone
from app.utils.text import normalize_text
from app.services.queue import enqueue_send_message
from app.services.webhook_ingress import enqueue_webhook_payload

router = APIRouter()
logger = logging.getLogger(__name__)



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

        if event_type == "send_message":
            text = str(event.get("text") or "").strip()
            if not text:
                continue
            logger.info("[FLOW SEND EVENT] tenant_id=%s wa_id=%s", tenant_uuid, wa_id)
            if event.get("after_delay") is True:
                logger.info("[FLOW SEND AFTER DELAY] tenant_id=%s wa_id=%s", tenant_uuid, wa_id)
            flow_id = None
            flow_version_id = None
            node_id = None
            if execution is not None:
                flow_version_id = execution.flow_version_id
                node_id = execution.current_node_id
                flow_version = db.get(FlowVersion, execution.flow_version_id)
                flow_id = flow_version.flow_id if flow_version else None
            conversation = (
                db.query(Conversation)
                .filter(Conversation.tenant_id == tenant_uuid, Conversation.phone_number == normalize_phone(phone))
                .order_by(Conversation.updated_at.desc())
                .first()
            )

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
                buttons=event.get("buttons") if isinstance(event.get("buttons"), list) else None,
                template_or_node_text=str(event.get("template_name") or event.get("node_label") or ""),
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

            tenant = (
                db.query(Tenant)
                .filter(Tenant.phone_number_id == phone_number_id)
                .first()
            )
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
                    contact_id=contact.id,
                )

            if existed:
                logger.info("Conversa encontrada id=%s", conversation.id)
            else:
                logger.info("Nenhuma conversa encontrada, criando nova para %s", normalized_phone)

            if contact_name and not conversation.name:
                conversation.name = contact_name
            ensure_conversation_contact_link(conversation, contact)

            if conversation.name is None and _looks_like_name(incoming_message):
                conversation.name = incoming_message.strip()
            if conversation.name and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
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
            await sse_broker.publish(f"{tenant.id}:{normalized_phone}", message_payload)
            await sse_broker.publish(f"{tenant.id}:{conversation.id}", message_payload)

            should_resolve_flow = conversation.mode != "flow" and (
                conversation.current_flow_id is None or conversation.current_node_id is None
            )
            if should_resolve_flow:
                resolved_flow = resolve_flow_for_message(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    message_text=incoming_message,
                    conversation=conversation,
                )
                if resolved_flow:
                    conversation.current_flow_id = resolved_flow.id
                    conversation.mode = "flow"
                    db.add(conversation)
                else:
                    logger.info("[FALLBACK ROUTING] tenant=%s conversation=%s", conversation.tenant_id, conversation.id)

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
