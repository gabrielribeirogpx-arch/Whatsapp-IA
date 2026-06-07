from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.flow_v2.channel_adapter import WhatsAppAdapter
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.models import FlowV2ScheduledJob, FlowV2Session
from app.flow_v2.runtime_worker import FlowV2RuntimeWorker, FlowV2WorkerResult

logger = logging.getLogger(__name__)


def _enqueue_whatsapp_text(
    *,
    recipient_id: str,
    text: str,
    tenant_id: Any | None = None,
    session_id: Any | None = None,
    conversation_id: Any | None = None,
    contact_id: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    from app.services.queue import enqueue_send_message

    payload = {
        "tenant_id": str(tenant_id or metadata.get("tenant_id") or ""),
        "provider_id": metadata.get("provider_id"),
        "phone": recipient_id,
        "text": text,
        "conversation_id": str(conversation_id or metadata.get("conversation_id") or "")
        or None,
        "contact_id": str(contact_id or metadata.get("contact_id") or "") or None,
        "session_id": str(session_id or metadata.get("session_id") or "") or None,
        "flow_id": metadata.get("flow_id"),
        "flow_version_id": metadata.get("flow_version_id"),
        "node_id": metadata.get("node_id"),
        "node_type": metadata.get("node_type"),
        "correlation_id": metadata.get("correlation_id")
        or metadata.get("message_id")
        or metadata.get("webhook_id")
        or metadata.get("delay_job_id"),
        "metadata": metadata,
        "flow_send_source": "flow_v2:delay_resume",
    }
    logger.info(
        "[DELAY RESUME ENQUEUE] tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s node_id=%s phone=%s metadata_keys=%s",
        payload.get("tenant_id") or "",
        payload.get("provider_id"),
        payload.get("session_id"),
        payload.get("conversation_id"),
        payload.get("contact_id"),
        payload.get("node_id"),
        recipient_id,
        sorted(metadata.keys()),
    )
    job_id = enqueue_send_message(payload)
    return {
        "status": "queued" if job_id else "skipped",
        "channel": "whatsapp",
        "type": "text",
        "recipient_id": recipient_id,
        "tenant_id": payload.get("tenant_id"),
        "job_id": job_id,
    }


@dataclass(frozen=True)
class DelayWorkerResult:
    processed: int
    resumed_session_ids: tuple[Any, ...]
    worker_results: tuple[FlowV2WorkerResult, ...]


class FlowV2DelayWorker:
    """Consumes due rows from flow_v2_scheduled_jobs and resumes Runtime V2."""

    def __init__(
        self,
        *,
        runtime_worker: FlowV2RuntimeWorker | None = None,
        event_store: FlowV2EventStore | None = None,
    ) -> None:
        self.runtime_worker = runtime_worker or FlowV2RuntimeWorker(
            channel_adapter=WhatsAppAdapter(client=_enqueue_whatsapp_text),
        )
        self.event_store = event_store or FlowV2EventStore()

    def run_due(
        self, db: Session, *, now: datetime | None = None, limit: int = 100
    ) -> DelayWorkerResult:
        now = (now or datetime.now(UTC)).replace(tzinfo=None)
        jobs = list(
            db.execute(
                select(FlowV2ScheduledJob)
                .where(FlowV2ScheduledJob.run_at <= now)
                .order_by(FlowV2ScheduledJob.run_at.asc())
                .limit(limit)
            ).scalars()
        )
        results: list[FlowV2WorkerResult] = []
        resumed_ids: list[Any] = []
        seen_job_ids: set[str] = set()
        for job in jobs:
            job_id = str(job.id)
            if job_id in seen_job_ids:
                continue
            seen_job_ids.add(job_id)
            session = db.execute(
                select(FlowV2Session).where(
                    FlowV2Session.id == job.session_id,
                    FlowV2Session.tenant_id == job.tenant_id,
                )
            ).scalar_one_or_none()
            if session is None:
                db.execute(
                    delete(FlowV2ScheduledJob).where(FlowV2ScheduledJob.id == job.id)
                )
                continue
            logger.info(
                "[DELAY RESUME BEFORE] job_id=%s session_id=%s current_node_id=%s session_status=%s resume_node_id=%s run_at=%s",
                job.id,
                session.id,
                session.current_node_id,
                session.status,
                job.resume_node_id,
                job.run_at,
            )
            session.current_node_id = job.resume_node_id
            session.status = str(FlowV2SessionStatus.RUNNING)
            logger.info(
                "[DELAY_RESUMED] after_move_to session_id=%s current_node_id=%s session_status=%s resume_node_id=%s job_id=%s",
                session.id,
                session.current_node_id,
                session.status,
                job.resume_node_id,
                job.id,
            )
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.DELAY_RESUMED,
                node_id=job.resume_node_id,
                payload={"job_id": job_id, "resume_node_id": job.resume_node_id},
            )
            runtime_input = RuntimeInput(
                tenant_id=session.tenant_id,
                flow_version_id=session.flow_version_id,
                external_user_id=session.external_user_id,
                contact_id=session.contact_id,
                conversation_id=session.conversation_id,
                metadata={
                    "delay_job_id": job_id,
                    "event_type": str(FlowV2EventType.DELAY_RESUMED),
                    "_flow_v2_session_id": str(session.id),
                },
            )
            results.append(self.runtime_worker.process(db, runtime_input))
            logger.info(
                "[DELAY RESUME AFTER] job_id=%s session_id=%s current_node_id=%s session_status=%s resume_node_id=%s",
                job.id,
                session.id,
                session.current_node_id,
                session.status,
                job.resume_node_id,
            )
            resumed_ids.append(session.id)
            db.execute(
                delete(FlowV2ScheduledJob).where(FlowV2ScheduledJob.id == job.id)
            )
        db.flush()
        return DelayWorkerResult(
            processed=len(resumed_ids),
            resumed_session_ids=tuple(resumed_ids),
            worker_results=tuple(results),
        )
