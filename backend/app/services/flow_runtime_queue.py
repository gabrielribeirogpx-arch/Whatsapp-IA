from __future__ import annotations

import logging
import os
from typing import Any

from redis import Redis
from rq import Queue, get_current_job

try:
    from rq import Retry
except ImportError:
    Retry = None

from app.db.session import SessionLocal
from app.models.conversation import Conversation
from app.services.flow_runtime_service import FlowRuntimeService
from app.services.job_queue_service import make_job_envelope, on_job_failure, unwrap_job_envelope

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLOW_RUNTIME_QUEUE_NAME = os.getenv("FLOW_RUNTIME_QUEUE", "default")


def run_flow_job(flow_id: str | dict[str, Any], conversation_id: str = "", message: str = "", message_id: str | None = None) -> dict[str, Any]:
    if isinstance(flow_id, dict):
        payload = unwrap_job_envelope(flow_id, expected_job_type="flow_execution")
        if payload is None:
            return {"status": "skipped"}
        flow_id = str(payload.get("flow_id") or "")
        conversation_id = str(payload.get("conversation_id") or "")
        message = str(payload.get("message") or "")
        message_id = str(payload.get("message_id") or "")
    job = get_current_job()
    logger.info(
        "[FLOW JOB START] job_id=%s flow_id=%s conversation_id=%s",
        getattr(job, "id", None),
        flow_id,
        conversation_id,
    )
    try:
        with SessionLocal() as db:
            service = FlowRuntimeService(db)
            result = service.execute_with_session(
                flow_id=str(flow_id),
                conversation_id=str(conversation_id),
                input_text=str(message or ""),
            )
            from app.services.whatsapp_service import (
                send_whatsapp_document_cloud,
                send_whatsapp_image_cloud,
                send_whatsapp_list_cloud,
                send_whatsapp_message_cloud,
                send_whatsapp_buttons,
            )

            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conversation:
                return result

            for msg in result.get("responses", []):
                if isinstance(msg, dict):
                    kind = str(msg.get("type") or "").lower()
                    if kind == "image":
                        send_whatsapp_image_cloud(conversation.phone_number, str(msg.get("media_url") or ""), str(msg.get("caption") or ""), tenant_id=str(conversation.tenant_id))
                    elif kind == "document":
                        send_whatsapp_document_cloud(conversation.phone_number, str(msg.get("document_url") or ""), str(msg.get("filename") or ""), str(msg.get("caption") or ""), tenant_id=str(conversation.tenant_id))
                    elif kind == "buttons":
                        send_whatsapp_buttons(conversation.phone_number, {"data": {"content": msg.get("body_text"), "buttons": msg.get("buttons") or []}}, tenant_id=str(conversation.tenant_id))
                    elif kind == "list":
                        send_whatsapp_list_cloud(conversation.phone_number, str(msg.get("body_text") or ""), msg.get("sections") or [], tenant_id=str(conversation.tenant_id))
                    continue
                send_whatsapp_message_cloud(conversation.phone_number, str(msg), tenant_id=str(conversation.tenant_id))

            logger.info(
                "[FLOW JOB END] job_id=%s flow_id=%s conversation_id=%s steps=%s status=%s",
                getattr(job, "id", None),
                flow_id,
                conversation_id,
                result.get("steps"),
                result.get("status"),
            )
            return result
    except Exception:
        logger.exception(
            "[FLOW ERROR] job_id=%s flow_id=%s conversation_id=%s",
            getattr(job, "id", None),
            flow_id,
            conversation_id,
        )
        raise


def _tenant_id_for_conversation(conversation_id: str) -> str | None:
    try:
        with SessionLocal() as db:
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            return str(conversation.tenant_id) if conversation else None
    except Exception:
        logger.warning("event=flow_execution_tenant_lookup_failed conversation_id=%s", conversation_id, exc_info=True)
        return None


def enqueue_run_flow_job(flow_id: str, conversation_id: str, message: str, message_id: str | None = None) -> str:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    queue = Queue(name=FLOW_RUNTIME_QUEUE_NAME, connection=redis_conn)

    job = queue.enqueue(
        run_flow_job,
        make_job_envelope("flow_execution", {"flow_id": str(flow_id), "conversation_id": str(conversation_id), "message": str(message or ""), "message_id": str(message_id or ""), "tenant_id": _tenant_id_for_conversation(str(conversation_id))}, idempotency_key=str(message_id or conversation_id)),
        retry=Retry(max=3, interval=[5, 15, 45]) if Retry else None,
        job_timeout=120,
        failure_ttl=86400,
        result_ttl=3600,
        on_failure=on_job_failure,
    )
    return str(job.id)


def enqueue_flow_job(flow_id: str, conversation_id: str, message: str, message_id: str | None = None) -> str:
    return enqueue_run_flow_job(flow_id=flow_id, conversation_id=conversation_id, message=message, message_id=message_id)
