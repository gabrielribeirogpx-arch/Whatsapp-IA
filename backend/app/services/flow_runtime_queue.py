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
from app.services.lock_service import ConversationLock
from app.services.flow_runtime_service import FlowRuntimeService

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLOW_RUNTIME_QUEUE_NAME = os.getenv("FLOW_RUNTIME_QUEUE", "default")


def run_flow_job(flow_id: str, conversation_id: str, message: str, message_id: str | None = None) -> dict[str, Any]:
    job = get_current_job()
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    lock_key = f"lock:{conversation_id}"
    lock = ConversationLock(redis_conn)
    if not lock.acquire(lock_key):
        logger.info("[FLOW LOCKED] conversation_id=%s", conversation_id)
        return {"status": "locked", "conversation_id": conversation_id}

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
            from app.services.whatsapp_service import send_whatsapp_message_cloud

            for msg in result.get("responses", []):
                logger.info("[FLOW SEND] conversation_id=%s", conversation_id)
                send_whatsapp_message_cloud(conversation_id, msg)

            logger.info(
                "[FLOW END] job_id=%s flow_id=%s conversation_id=%s steps=%s status=%s",
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
    finally:
        lock.release(lock_key)


def enqueue_run_flow_job(flow_id: str, conversation_id: str, message: str, message_id: str | None = None) -> str:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    queue = Queue(name=FLOW_RUNTIME_QUEUE_NAME, connection=redis_conn)

    job = queue.enqueue(
        run_flow_job,
        str(flow_id),
        str(conversation_id),
        str(message or ""),
        str(message_id or ""),
        retry=Retry(max=3, interval=[5, 15, 45]) if Retry else None,
        failure_ttl=86400,
        result_ttl=3600,
    )
    return str(job.id)


def enqueue_flow_job(flow_id: str, conversation_id: str, message: str, message_id: str | None = None) -> str:
    return enqueue_run_flow_job(flow_id=flow_id, conversation_id=conversation_id, message=message, message_id=message_id)
