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
from app.services.flow_runtime_service import FlowRuntimeService

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLOW_RUNTIME_QUEUE_NAME = os.getenv("FLOW_RUNTIME_QUEUE", "default")


def run_flow_job(flow_id: str, conversation_id: str, message: str) -> dict[str, Any]:
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


def enqueue_run_flow_job(flow_id: str, conversation_id: str, message: str) -> str:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    queue = Queue(name=FLOW_RUNTIME_QUEUE_NAME, connection=redis_conn)

    job = queue.enqueue(
        run_flow_job,
        str(flow_id),
        str(conversation_id),
        str(message or ""),
        retry=Retry(max=3, interval=[5, 15, 45]) if Retry else None,
        failure_ttl=86400,
        result_ttl=3600,
    )
    return str(job.id)
