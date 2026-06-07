from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.models import FlowV2ScheduledJob, FlowV2Session
from app.flow_v2.runtime_worker import FlowV2RuntimeWorker, FlowV2WorkerResult

logger = logging.getLogger(__name__)


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
        self.runtime_worker = runtime_worker or FlowV2RuntimeWorker()
        self.event_store = event_store or FlowV2EventStore()

    def run_due(self, db: Session, *, now: datetime | None = None, limit: int = 100) -> DelayWorkerResult:
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
        for job in jobs:
            session = db.execute(
                select(FlowV2Session).where(FlowV2Session.id == job.session_id, FlowV2Session.tenant_id == job.tenant_id)
            ).scalar_one_or_none()
            if session is None:
                db.execute(delete(FlowV2ScheduledJob).where(FlowV2ScheduledJob.id == job.id))
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
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.DELAY_RESUMED,
                node_id=job.resume_node_id,
                payload={"job_id": str(job.id), "resume_node_id": job.resume_node_id},
            )
            runtime_input = RuntimeInput(
                tenant_id=session.tenant_id,
                flow_version_id=session.flow_version_id,
                external_user_id=session.external_user_id,
                contact_id=session.contact_id,
                conversation_id=session.conversation_id,
                metadata={"delay_job_id": str(job.id), "event_type": str(FlowV2EventType.DELAY_RESUMED)},
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
            db.execute(delete(FlowV2ScheduledJob).where(FlowV2ScheduledJob.id == job.id))
        db.flush()
        return DelayWorkerResult(processed=len(resumed_ids), resumed_session_ids=tuple(resumed_ids), worker_results=tuple(results))
