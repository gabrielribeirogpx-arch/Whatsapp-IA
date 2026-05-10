from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.flow import Flow
from app.models.flow_session import FlowSession

SESSION_TTL_MINUTES = 30
FINAL_SESSION_STATUSES = {"finished", "expired", "cancelled"}
FINAL_COMPLETION_STATUSES = {"completed", "abandoned", "conversion", "expired"}


class FlowSessionService:
    def __init__(self, db):
        self.db = db

    def get_or_create_session(self, flow_id: str, conversation_id: str) -> FlowSession:
        session = self.db.query(FlowSession).filter_by(
            flow_id=flow_id,
            conversation_id=conversation_id,
        ).first()

        logger_payload = {"tenant_id": str(tenant_id), "user_identifier": user_identifier, "flow_id": str(flow.id)}
        print(f"[FLOW SESSION SAVE] {logger_payload} current_node_id={current_node_id}")
        if not session:
            session = FlowSession(
                flow_id=flow_id,
                conversation_id=conversation_id,
                status="running",
                context={},
            )
            self.db.add(session)
            self.db.commit()
            self.db.refresh(session)

        return session

    def get_runtime_session(self, tenant_id, user_identifier: str, flow: Flow) -> tuple[FlowSession | None, str | None]:
        session = (
            self.db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == user_identifier,
                FlowSession.flow_id == flow.id,
            )
            .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
            .first()
        )
        print(f"[SESSION LOAD] tenant_id={tenant_id} user={user_identifier} found={bool(session)}")
        if not session:
            return None, "missing"

        now = datetime.now(UTC)
        updated_at = session.updated_at
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        if updated_at and now - updated_at > timedelta(minutes=SESSION_TTL_MINUTES):
            print(f"[SESSION INVALID] reason=expired session_id={session.id}")
            return session, "expired"

        if (session.status or "").lower() in FINAL_SESSION_STATUSES:
            print(f"[SESSION INVALID] reason=finalized status={session.status} session_id={session.id}")
            return session, "finalized"

        session_version_id = getattr(session, "flow_version_id", None)
        if session_version_id is None:
            # Legacy sessions created before flow_version_id hardening are not
            # recoverable in a version-pinned model.
            print(f"[SESSION INVALID] reason=missing_session_version session_id={session.id}")
            return session, "missing_session_version"

        return session, None



    def get_runtime_session_state(self, tenant_id, phone: str, flow_id) -> dict[str, Any]:
        session = self.get_latest_session_for_flow(tenant_id=tenant_id, user_identifier=phone, flow_id=flow_id)
        exists = session is not None
        status = ((getattr(session, "status", "") or "").strip().lower()) if session else ""
        current_node_id = getattr(session, "current_node_id", None) if session else None

        is_active = bool(session and status in {"running", "active"} and current_node_id is not None)
        is_finalized = bool(session and (status in {"completed", "finalized", "expired"} or current_node_id is None))

        print(
            "[SESSION STATE RESOLVED] "
            f"session_id={getattr(session, 'id', 'none')} "
            f"status={status or 'none'} "
            f"current_node_id={current_node_id} "
            f"exists={exists} "
            f"is_active={is_active} "
            f"is_finalized={is_finalized}"
        )

        return {
            "session": session,
            "exists": exists,
            "status": status,
            "is_active": is_active,
            "is_finalized": is_finalized,
        }
    def get_latest_session_for_flow(self, *, tenant_id, user_identifier: str, flow_id) -> FlowSession | None:
        return (
            self.db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == user_identifier,
                FlowSession.flow_id == flow_id,
            )
            .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
            .first()
        )

    def save_runtime_session(self, *, tenant_id, user_identifier: str, flow: Flow, current_node_id, status: str = "running", context: dict[str, Any] | None = None, variables: dict[str, Any] | None = None) -> FlowSession:
        session = (
            self.db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == user_identifier,
                FlowSession.flow_id == flow.id,
            )
            .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
            .first()
        )
        logger_payload = {"tenant_id": str(tenant_id), "user_identifier": user_identifier, "flow_id": str(flow.id)}
        print(f"[FLOW SESSION SAVE] {logger_payload} current_node_id={current_node_id}")
        safe_current_node_id = str(current_node_id) if current_node_id else None
        if (
            session
            and (session.status or "").lower() in {"running", "active"}
            and safe_current_node_id is None
            and session.current_node_id is not None
            and str(status or "").lower() not in {"completed", "finalized", "expired", "finished"}
        ):
            print(
                "[SESSION CURRENT_NODE_NULL_OVERWRITE_BLOCKED] "
                f"session_id={session.id} previous_current_node_id={session.current_node_id} requested_status={status}"
            )
            safe_current_node_id = str(session.current_node_id)

        if not session:
            session = FlowSession(
                tenant_id=tenant_id,
                user_identifier=user_identifier,
                flow_id=flow.id,
                flow_version_id=getattr(flow, "published_version_id", None),
                current_node_id=safe_current_node_id,
                status=status,
                context=context or {},
                variables={"flow_version": flow.version, "flow_version_id": str(getattr(flow, "published_version_id", "") or ""), **(variables or {})},
            )
            self.db.add(session)
        else:
            print(
                "[SESSION CURRENT_NODE BEFORE UPDATE] "
                f"session_id={session.id} current_node_id={session.current_node_id} requested_current_node_id={safe_current_node_id}"
            )
            session.current_node_id = safe_current_node_id
            # Keep session pinned to the version it started with.
            if session.flow_version_id is None:
                session.flow_version_id = getattr(flow, "published_version_id", None)
            session.status = status
            session.context = context if context is not None else (session.context or {})
            merged_variables = dict(session.variables or {})
            merged_variables["flow_version"] = flow.version
            merged_variables["flow_version_id"] = str(getattr(flow, "published_version_id", "") or "")
            if variables:
                merged_variables.update(variables)
            session.variables = merged_variables
            print(
                "[SESSION CURRENT_NODE AFTER UPDATE] "
                f"session_id={session.id} current_node_id={session.current_node_id}"
            )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        print(f"[FLOW SESSION COMMIT] session_id={session.id} current_node_id={session.current_node_id}")
        print(
            "[FLOW SESSION SAVE OK] "
            f"current_node_id={session.current_node_id} "
            f"session_version={getattr(session, 'flow_version_id', None)} "
            f"published_version={getattr(flow, 'published_version_id', None)}"
        )
        return session

    def clear_runtime_session(self, tenant_id, user_identifier: str, flow: Flow, reason: str = "manual_reset") -> None:
        sessions = (
            self.db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == user_identifier,
                FlowSession.flow_id == flow.id,
            )
            .all()
        )
        for session in sessions:
            session.status = "expired"
            session.current_node_id = None
            if reason:
                metadata = dict(session.variables or {})
                metadata["abandon_reason"] = reason
                session.variables = metadata
        self.db.commit()
        print(f"[SESSION RESET] reason={reason} tenant_id={tenant_id} user={user_identifier} count={len(sessions)}")

    def update_session(self, session: FlowSession, node_id: str | None, context: dict | None = None, status: str | None = None) -> None:
        next_status = str(status or session.status or "").lower()
        safe_node_id = node_id
        print(
            "[SESSION CURRENT_NODE BEFORE UPDATE] "
            f"session_id={session.id} current_node_id={session.current_node_id} requested_current_node_id={node_id} status={next_status}"
        )
        if (
            (session.status or "").lower() in {"running", "active"}
            and node_id is None
            and session.current_node_id is not None
            and next_status not in {"completed", "finalized", "expired", "finished"}
        ):
            print(
                "[SESSION CURRENT_NODE_NULL_OVERWRITE_BLOCKED] "
                f"session_id={session.id} previous_current_node_id={session.current_node_id} requested_status={next_status}"
            )
            safe_node_id = session.current_node_id
        session.current_node_id = safe_node_id

        if context is not None:
            session.context = context

        if status:
            session.status = status

        self.db.commit()
        self.db.refresh(session)
        print(
            "[SESSION CURRENT_NODE AFTER UPDATE] "
            f"session_id={session.id} current_node_id={session.current_node_id} status={session.status}"
        )

    def reset_runtime_state_for_user_flow(self, *, tenant_id, user_identifier: str, flow_id) -> tuple[int, list]:
        sessions = (
            self.db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == user_identifier,
                FlowSession.flow_id == flow_id,
            )
            .all()
        )
        session_ids = []
        for session in sessions:
            session_ids.append(session.id)
            session.status = "completed"
            session.current_node_id = None
            session.context = {}
            session.variables = {}
        self.db.commit()
        return len(sessions), session_ids

    def end_session(
        self,
        session: FlowSession,
        *,
        status: str,
        ended_at: datetime | None = None,
    ) -> FlowSession:
        normalized_status = (status or "").lower()
        if normalized_status not in FINAL_COMPLETION_STATUSES:
            raise ValueError(f"Invalid status '{status}'")

        if (session.status or "").lower() in FINAL_SESSION_STATUSES:
            return session

        if normalized_status == "completed":
            session.status = "finished"
        elif normalized_status in {"abandoned", "expired"}:
            session.status = "expired"
        elif normalized_status == "conversion":
            session.status = "finished"
            marker_time = ended_at or datetime.utcnow()
            metadata = dict(session.variables or {})
            metadata["conversion_at"] = marker_time.isoformat()
            session.variables = metadata

        return session
