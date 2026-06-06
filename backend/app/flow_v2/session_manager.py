from __future__ import annotations

from datetime import datetime
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.models import FlowV2Session
from app.flow_v2.snapshot import FlowV2Snapshot

logger = logging.getLogger(__name__)


class FlowV2SessionManager:
    """Creates and advances the minimal Runtime V2 session pointer."""

    def __init__(self, event_store: FlowV2EventStore | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()

    def get_or_create(
        self,
        db: Session,
        *,
        runtime_input: RuntimeInput,
        snapshot: FlowV2Snapshot,
    ) -> FlowV2Session:
        session = db.execute(
            select(FlowV2Session)
            .where(
                FlowV2Session.tenant_id == runtime_input.tenant_id,
                FlowV2Session.flow_version_id == runtime_input.flow_version_id,
                FlowV2Session.external_user_id == runtime_input.external_user_id,
                FlowV2Session.status.in_([FlowV2SessionStatus.RUNNING, FlowV2SessionStatus.WAITING]),
            )
            .order_by(FlowV2Session.started_at.desc())
        ).scalar_one_or_none()
        if session is not None:
            logger.info(
                "[CHOICE SESSION FOUND] session_id=%s status=%s current_node_id=%s flow_version_id=%s external_user_id=%s incoming_selected_row_id=%s incoming_row_id=%s incoming_sourceHandle=%s",
                session.id,
                session.status,
                session.current_node_id,
                runtime_input.flow_version_id,
                runtime_input.external_user_id,
                runtime_input.metadata.get("selected_row_id"),
                runtime_input.metadata.get("row_id"),
                runtime_input.metadata.get("sourceHandle"),
            )
            return session

        session = FlowV2Session(
            tenant_id=runtime_input.tenant_id,
            flow_version_id=runtime_input.flow_version_id,
            contact_id=runtime_input.contact_id,
            conversation_id=runtime_input.conversation_id,
            external_user_id=runtime_input.external_user_id,
            status=FlowV2SessionStatus.RUNNING,
            current_node_id=snapshot.start_node_id,
        )
        db.add(session)
        db.flush()
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.SESSION_STARTED,
            payload={"snapshot_hash": snapshot.hash, "start_node_id": snapshot.start_node_id},
        )
        return session

    def move_to(self, db: Session, *, session: FlowV2Session, node_id: str | None, status: FlowV2SessionStatus) -> None:
        session.current_node_id = node_id
        session.status = str(status)
        session.updated_at = datetime.utcnow()
        db.add(session)
