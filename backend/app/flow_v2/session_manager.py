from __future__ import annotations

from datetime import datetime
import logging
from uuid import UUID

from sqlalchemy import case, select, text
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
        raw_session_id = runtime_input.metadata.get("_flow_v2_session_id")
        session_id = UUID(str(raw_session_id)) if raw_session_id else None
        if session_id:
            session = db.execute(
                select(FlowV2Session).where(
                    FlowV2Session.id == session_id,
                    FlowV2Session.tenant_id == runtime_input.tenant_id,
                    FlowV2Session.flow_version_id == runtime_input.flow_version_id,
                    FlowV2Session.external_user_id == runtime_input.external_user_id,
                )
            ).scalar_one_or_none()
            if session is not None:
                return session

        self._lock_active_session_identity(db, runtime_input=runtime_input)
        auto_restart = _metadata_allows_auto_restart(runtime_input.metadata)
        restart_requested = _metadata_requests_restart(runtime_input.metadata)
        session_filters = {
            "tenant_id": str(runtime_input.tenant_id),
            "flow_version_id": str(runtime_input.flow_version_id),
            "external_user_id": runtime_input.external_user_id,
            "conversation_id": str(runtime_input.conversation_id) if runtime_input.conversation_id else None,
            "contact_id": str(runtime_input.contact_id) if runtime_input.contact_id else None,
            "statuses": "all",
        }
        logger.info(
            "event=flow_v2_session_lookup tenant_id=%s conversation_id=%s contact_id=%s phone=%s flow_version_id=%s filters=%s",
            runtime_input.tenant_id,
            runtime_input.conversation_id,
            runtime_input.contact_id,
            runtime_input.external_user_id,
            runtime_input.flow_version_id,
            session_filters,
        )
        session_query = (
            select(FlowV2Session)
            .where(
                FlowV2Session.tenant_id == runtime_input.tenant_id,
                FlowV2Session.flow_version_id == runtime_input.flow_version_id,
                FlowV2Session.external_user_id == runtime_input.external_user_id,
            )
            .order_by(
                case((FlowV2Session.status.in_([str(FlowV2SessionStatus.RUNNING), str(FlowV2SessionStatus.WAITING)]), 0), else_=1),
                FlowV2Session.updated_at.desc(),
                FlowV2Session.started_at.desc(),
            )
            .limit(2)
        )
        matched_sessions = db.execute(session_query).scalars().all()
        if len(matched_sessions) > 1:
            logger.warning(
                "MESSAGE_WORKER_MULTIPLE_RESULTS_DETECTED entity=flow_v2_sessions selected_session_id=%s duplicate_session_id=%s tenant_id=%s conversation_id=%s contact_id=%s phone=%s flow_version_id=%s filters=%s",
                matched_sessions[0].id,
                matched_sessions[1].id,
                runtime_input.tenant_id,
                runtime_input.conversation_id,
                runtime_input.contact_id,
                runtime_input.external_user_id,
                runtime_input.flow_version_id,
                session_filters,
            )
        session = matched_sessions[0] if matched_sessions else None
        previous_session_id = getattr(session, "id", None) if session is not None else None
        if session is not None and restart_requested and str(session.status) in {str(FlowV2SessionStatus.RUNNING), str(FlowV2SessionStatus.WAITING)}:
            session.status = str(FlowV2SessionStatus.COMPLETED)
            session.updated_at = datetime.utcnow()
            db.add(session)
            db.flush()
            logger.info(
                "event=flow_restart_keyword_detected previous_session_id=%s new_session_id=%s reason=restart_keyword",
                session.id,
                None,
            )
            session = None

        if session is not None and str(session.status) in {str(FlowV2SessionStatus.RUNNING), str(FlowV2SessionStatus.WAITING)}:
            if str(session.status) == str(FlowV2SessionStatus.WAITING):
                logger.info(
                    "[FLOW SESSION CONTINUE] session_id=%s node_id=%s reason=incoming_message_waiting_session",
                    session.id,
                    session.current_node_id,
                )
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
        if session is not None and str(session.status) == str(FlowV2SessionStatus.COMPLETED) and not auto_restart:
            logger.info(
                "[SESSION RESTART BLOCKED] session_id=%s status=%s current_node_id=%s flow_version_id=%s external_user_id=%s reason=finished_auto_restart_disabled",
                session.id,
                session.status,
                session.current_node_id,
                runtime_input.flow_version_id,
                runtime_input.external_user_id,
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
        if restart_requested:
            logger.info(
                "event=flow_restart_keyword_detected previous_session_id=%s new_session_id=%s reason=restart_keyword",
                previous_session_id,
                session.id,
            )
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.SESSION_STARTED,
            payload={"snapshot_hash": snapshot.hash, "start_node_id": snapshot.start_node_id},
        )
        return session

    def _lock_active_session_identity(self, db: Session, *, runtime_input: RuntimeInput) -> None:
        lock_key = ":".join(
            (
                str(runtime_input.tenant_id),
                str(runtime_input.flow_version_id),
                runtime_input.external_user_id,
            )
        )
        try:
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": lock_key},
            )
        except Exception:
            return

    def move_to(self, db: Session, *, session: FlowV2Session, node_id: str | None, status: FlowV2SessionStatus) -> None:
        previous_status = session.status
        previous_node_id = session.current_node_id
        session.current_node_id = node_id
        session.status = str(status)
        session.updated_at = datetime.utcnow()
        logger.info(
            "[SESSION STATE TRANSITION] session_id=%s status=%s->%s state=%s->%s node_id=%s->%s",
            session.id,
            previous_status,
            session.status,
            _state_label(previous_status),
            _state_label(session.status),
            previous_node_id,
            node_id,
        )
        db.add(session)


def _metadata_requests_restart(metadata: dict | None) -> bool:
    return bool((metadata or {}).get("restart_keyword"))


def _metadata_allows_auto_restart(metadata: dict | None) -> bool:
    value = (metadata or {}).get("auto_restart_flow", (metadata or {}).get("autoRestartFlow"))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
    return False


def _state_label(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == str(FlowV2SessionStatus.RUNNING):
        return "ACTIVE"
    if normalized == str(FlowV2SessionStatus.WAITING):
        return "WAITING"
    if normalized == str(FlowV2SessionStatus.COMPLETED):
        return "FINISHED"
    return normalized.upper() or "UNKNOWN"
