from datetime import datetime
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
from app.services.message_service import normalize_meta_message
from app.services.realtime_service import sse_broker
from app.services.flow_service import resolve_flow_for_message
from app.services.flow_engine_service import get_flow_graph
from app.services.flow_engine import get_node_by_id
from app.services.flow_session_service import FlowSessionService
from app.models.flow import Flow
from app.services.whatsapp_service import send_whatsapp_buttons, send_whatsapp_message_simple
from app.services.intent_service import classify_intent, normalize_input, route_intent
from app.models import Tenant
from app.utils.phone import normalize_phone
from app.utils.text import normalize_text

router = APIRouter()
logger = logging.getLogger(__name__)


def _extract_node_content(node: dict | None) -> str:
    if not isinstance(node, dict):
        return ""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    content = (
        data.get("content")
        or data.get("text")
        or node.get("content")
        or node.get("text")
        or ""
    )
    return str(content).strip()


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
                    send_whatsapp_message_simple(
                        normalize_phone(incoming["phone"]),
                        "Tive um problema aqui 😅 mas já estou corrigindo. Pode tentar de novo?",
                    )
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
    tenant_id = request.headers.get("X-Tenant-ID")

    if not tenant_id:
        tenant_id = "619474df-9dc1-4cd6-bce0-57a9402284bf"

    print("[TENANT USADO]:", tenant_id)

    payload = await _parse_webhook_payload(request)
    if not payload:
        return {"status": "ignored"}

    entry = (payload.get("entry") or [None])[0] or {}
    changes = (entry.get("changes") or [None])[0] or {}
    value = changes.get("value") or {}
    if not value.get("messages"):
        return {"status": "ignored"}
    message = value["messages"][0]

    wa_id = message["from"]
    phone = normalize_phone(wa_id)
    message_id = (message.get("id") or "").strip()
    if message["type"] == "interactive":
        user_input = message["interactive"]["button_reply"]["id"]
    elif message["type"] == "text":
        user_input = message["text"]["body"]
    else:
        user_input = ""

    user_input = normalize_input(user_input)
    print("[USER INPUT]:", user_input)
    intent = classify_intent(user_input)
    print("[INTENT]:", intent)

    tenant_uuid = UUID(tenant_id)
    was_inserted = register_processed_message(db=db, tenant_id=tenant_uuid, message_id=message_id)
    if not was_inserted:
        logger.info(
            "[WEBHOOK DUPLICATE SKIPPED] message_id=%s tenant_id=%s wa_id=%s",
            message_id,
            tenant_id,
            wa_id,
        )
        return {"status": "ignored"}

    redis_client = get_redis_client()
    lock_key = f"flow_lock:{tenant_uuid}:{wa_id}"
    lock_token = str(uuid.uuid4())
    lock_acquired = redis_client.set(lock_key, lock_token, nx=True, ex=10)
    if not lock_acquired:
        logger.info("[RUNTIME LOCKED] tenant_id=%s wa_id=%s", tenant_uuid, wa_id)
        return {"status": "ignored"}

    try:
        flow_row = (
            db.query(Flow)
            .filter(Flow.tenant_id == tenant_uuid, Flow.is_active.is_(True))
            .order_by(Flow.created_at.asc(), Flow.id.asc())
            .first()
        )
        if not flow_row:
            return {"status": "ignored"}

        published_version = (
            db.query(FlowVersion)
            .filter(FlowVersion.flow_id == flow_row.id, FlowVersion.is_published.is_(True))
            .order_by(FlowVersion.version.desc())
            .first()
        )
        if not published_version:
            return {"status": "ignored"}

        flow = {"nodes": published_version.nodes or [], "edges": published_version.edges or []}
        start_node = _find_start_node(flow["nodes"])
        if not start_node:
            print("[FLOW ERROR] START_NODE_NOT_FOUND")
            return {"status": "ignored"}

        execution = (
            db.query(FlowExecution)
            .filter(FlowExecution.flow_version_id == published_version.id, FlowExecution.user_phone == phone)
            .first()
        )
        if not execution:
            start_content = _extract_node_content(start_node)
            print("[FLOW RUNTIME] new_session=true")
            print("[FLOW RUNTIME] start_node_id=", start_node.get("id"))
            print("[FLOW RUNTIME] start_content=", start_content)
            if not start_content:
                print("[FLOW ERROR] EMPTY_START_CONTENT")
            else:
                try:
                    wa_response = send_whatsapp_message_simple(phone, start_content)
                    status_code = getattr(wa_response, "status_code", "unknown")
                    response_body = getattr(wa_response, "text", "")
                    print(f"[WHATSAPP SEND] to={phone} status={status_code}")
                    if response_body:
                        print(f"[WHATSAPP SEND BODY] {response_body[:500]}")
                except Exception as send_exc:
                    print(f"[WHATSAPP SEND ERROR] to={phone} error={send_exc}")

            next_node_id = _find_next_node_id(start_node.get("id"), flow["edges"])
            execution = FlowExecution(
                flow_version_id=published_version.id,
                user_phone=phone,
                current_node_id=next_node_id,
                state={},
            )
            db.add(execution)
            db.commit()
            db.refresh(execution)
            print("[FLOW RUNTIME] next_node_id=", next_node_id)
            return {"status": "message processed"}

        normalized = normalize_text(user_input)
        force_start = normalized in {"oi", "ola", "menu", "iniciar", "inicio", "reiniciar", "reset"}
        print("[RUNTIME FORCE START]", force_start)

        if force_start:
            start_content = _extract_node_content(start_node)
            print("[RUNTIME START NODE FOUND]", start_node.get("id"))
            print("[RUNTIME START CONTENT]", start_content)
            if start_content:
                send_whatsapp_message_simple(phone, start_content)
            next_node_id = _find_next_node_id(start_node.get("id"), flow["edges"])
            execution.current_node_id = next_node_id
            db.add(execution)
            db.commit()
            print("[RUNTIME SESSION OVERRIDDEN]")
            print("[WHATSAPP RESPONSE START]")
            return {"status": "message processed"}

        current_node = get_node_by_id(flow, execution.current_node_id)
        if not current_node:
            current_node = start_node

        def process_node(node: dict, user_input_value: str) -> str | None:
            node_type = str(node.get("type") or "").lower()
            if node_type == "message":
                edge = next((e for e in flow["edges"] if e.get("source") == node.get("id")), None)
                return edge.get("target") if edge else None
            if node_type == "condition":
                keywords = (node.get("data") or {}).get("keywords") or []
                match = any(str(k).lower() in user_input_value.lower() for k in keywords)
                desired = "true" if match else "false"
                edge = next((e for e in flow["edges"] if e.get("source") == node.get("id") and str(e.get("sourceHandle") or "").lower() == desired), None)
                return edge.get("target") if edge else None
            edge = next((e for e in flow["edges"] if e.get("source") == node.get("id")), None)
            return edge.get("target") if edge else None

        print("[FLOW EXECUTION]", execution.id)
        print("[FLOW VERSION]", published_version.version)
        print("[USER INPUT]", user_input)
        print("[CURRENT NODE]", current_node.get("id"))

        next_node_id = process_node(current_node, user_input)
        print("[NEXT NODE]", next_node_id)

        execution.current_node_id = next_node_id
        db.add(execution)
        db.commit()

        next_node = get_node_by_id(flow, next_node_id) if next_node_id else None
        if next_node:
            node_message = (next_node.get("data") or {}).get("content") or (next_node.get("data") or {}).get("text")
            if node_message:
                send_whatsapp_message_simple(phone, node_message)
        return {"status": "message processed"}
    except Exception:
        db.rollback()
        send_whatsapp_message_simple(phone, "⚠️ O sistema está inicializando. Tente novamente em instantes.")
        return {"status": "fallback"}
    finally:
        try:
            redis_client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                lock_key,
                lock_token,
            )
        except Exception:
            logger.exception("[RUNTIME LOCK RELEASE ERROR] tenant_id=%s wa_id=%s", tenant_uuid, wa_id)


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
    tenant_id = _resolve_request_tenant_id(request)
    query = (
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.phone_number, Conversation.created_at, Conversation.tenant_id))
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    )
    if tenant_id:
        query = query.where(Conversation.tenant_id == tenant_id)

    conversations = db.execute(query).scalars().all()

    response: list[dict[str, str | None]] = []
    for conversation in conversations:
        last_message = db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
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
    tenant_id = _resolve_request_tenant_id(request)
    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    if tenant_id:
        query = query.where(Message.tenant_id == tenant_id)
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
