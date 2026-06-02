from __future__ import annotations

from datetime import UTC, datetime, timedelta
import traceback
from typing import Any

from app.models.flow import Flow
from app.models.flow_session import FlowSession, set_current_node_write_reason

SESSION_TTL_MINUTES = 30
FINAL_SESSION_STATUSES = {"finished", "expired", "cancelled"}
FINAL_COMPLETION_STATUSES = {"completed", "abandoned", "conversion", "expired"}
ALLOWED_NULL_CURRENT_NODE_REASONS = {"flow_finished", "terminal_node", "no_outgoing_edge", "manual_reset"}


def _context_flow_current_node_id(context: dict[str, Any] | None) -> Any:
    return context.get("flow_current_node_id") if isinstance(context, dict) else None


def _log_session_node(
    phase: str,
    *,
    session: FlowSession | None,
    current_node_id: Any = None,
    flow_current_node_id: Any = None,
    executed_node_id: Any = None,
    next_node_id: Any = None,
    status: Any = None,
    reason: str | None = None,
) -> None:
    resolved_current_node_id = (
        current_node_id
        if current_node_id is not None
        else getattr(session, "current_node_id", None)
    )
    resolved_flow_current_node_id = (
        flow_current_node_id
        if flow_current_node_id is not None
        else _context_flow_current_node_id(getattr(session, "context", None))
    )
    print(
        f"[SESSION NODE {phase}] "
        f"session_id={getattr(session, 'id', None)} "
        f"current_node_id={resolved_current_node_id} "
        f"flow_current_node_id={resolved_flow_current_node_id} "
        f"node_id_executado={executed_node_id} "
        f"next_node_id={next_node_id} "
        f"status={status if status is not None else getattr(session, 'status', None)} "
        f"reason={reason or ''}"
    )


class FlowSessionService:
    def __init__(self, db):
        self.db = db

    def get_or_create_session(self, flow_id: str, conversation_id: str) -> FlowSession:
        session = self.db.query(FlowSession).filter_by(
            flow_id=flow_id,
            conversation_id=conversation_id,
        ).first()

        print(
            f"[FLOW SESSION GET_OR_CREATE] flow_id={flow_id} "
            f"conversation_id={conversation_id} found={bool(session)} "
            f"current_node_id={getattr(session, 'current_node_id', None)}"
        )
        _log_session_node(
            "BEFORE",
            session=session,
            executed_node_id=None,
            next_node_id=getattr(session, "current_node_id", None),
            reason="get_or_create_session",
        )
        if not session:
            session = FlowSession(
                flow_id=flow_id,
                conversation_id=conversation_id,
                status="running",
                context={},
            )
            self.db.add(session)
            _log_session_node(
                "AFTER",
                session=session,
                executed_node_id=None,
                next_node_id=session.current_node_id,
                reason="get_or_create_session",
            )
            self.db.commit()
            self.db.refresh(session)
            _log_session_node(
                "PERSIST",
                session=session,
                executed_node_id=None,
                next_node_id=session.current_node_id,
                reason="get_or_create_session",
            )
        else:
            _log_session_node(
                "AFTER",
                session=session,
                executed_node_id=None,
                next_node_id=session.current_node_id,
                reason="get_or_create_session",
            )

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
        if current_node_id is None and isinstance(getattr(session, "variables", None), dict):
            current_node_id = session.variables.get("current_node_id")

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

    def save_runtime_session(
        self,
        *,
        tenant_id,
        user_identifier: str,
        flow: Flow,
        current_node_id,
        status: str = "running",
        context: dict[str, Any] | None = None,
        variables: dict[str, Any] | None = None,
        executed_node_id: Any = None,
        next_node_id: Any = None,
    ) -> FlowSession:
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
        requested_next_node_id = next_node_id if next_node_id is not None else current_node_id
        _log_session_node(
            "BEFORE",
            session=session,
            flow_current_node_id=_context_flow_current_node_id(context),
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            status=status,
            reason="save_runtime_session",
        )
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
            session.current_node_id = self.safe_update_current_node(
                session=session,
                next_node_id=safe_current_node_id,
                reason="save_runtime_session",
            )
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
        _log_session_node(
            "AFTER",
            session=session,
            flow_current_node_id=_context_flow_current_node_id(context if context is not None else getattr(session, "context", None)),
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            status=status,
            reason="save_runtime_session",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        print(f"[FLOW SESSION COMMIT] session_id={session.id} current_node_id={session.current_node_id}")
        _log_session_node(
            "PERSIST",
            session=session,
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            reason="save_runtime_session",
        )
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
            _log_session_node(
                "BEFORE",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                status=session.status,
                reason=reason or "manual_reset",
            )
            session.current_node_id = self.safe_update_current_node(
                session=session,
                next_node_id=None,
                reason=reason or "manual_reset",
                graph_context={"executed_node_id": session.current_node_id},
            )
            _log_session_node(
                "AFTER",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                status=session.status,
                reason=reason or "manual_reset",
            )
            if reason:
                metadata = dict(session.variables or {})
                metadata["abandon_reason"] = reason
                session.variables = metadata
        self.db.commit()
        for session in sessions:
            _log_session_node(
                "PERSIST",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                reason=reason or "manual_reset",
            )
        print(f"[SESSION RESET] reason={reason} tenant_id={tenant_id} user={user_identifier} count={len(sessions)}")

    def update_session(
        self,
        session: FlowSession,
        node_id: str | None,
        context: dict | None = None,
        status: str | None = None,
        executed_node_id: Any = None,
        next_node_id: Any = None,
    ) -> None:
        next_status = str(status or session.status or "").lower()
        safe_node_id = node_id
        requested_next_node_id = next_node_id if next_node_id is not None else node_id
        _log_session_node(
            "BEFORE",
            session=session,
            flow_current_node_id=_context_flow_current_node_id(context),
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            status=next_status,
            reason="update_session",
        )
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
        session.current_node_id = self.safe_update_current_node(
            session=session,
            next_node_id=safe_node_id,
            reason="update_session",
        )

        if context is not None:
            session.context = context

        if status:
            session.status = status

        _log_session_node(
            "AFTER",
            session=session,
            flow_current_node_id=_context_flow_current_node_id(context if context is not None else getattr(session, "context", None)),
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            status=session.status,
            reason="update_session",
        )
        self.db.commit()
        self.db.refresh(session)
        print(
            "[SESSION CURRENT_NODE AFTER UPDATE] "
            f"session_id={session.id} current_node_id={session.current_node_id} status={session.status}"
        )
        _log_session_node(
            "PERSIST",
            session=session,
            executed_node_id=executed_node_id,
            next_node_id=requested_next_node_id,
            reason="update_session",
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
            _log_session_node(
                "BEFORE",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                status=session.status,
                reason="reset_runtime_state_for_user_flow",
            )
            session.current_node_id = self.safe_update_current_node(
                session=session,
                next_node_id=None,
                reason="manual_reset",
                graph_context={"executed_node_id": session.current_node_id},
            )
            session.context = {}
            session.variables = {}
            _log_session_node(
                "AFTER",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                status=session.status,
                reason="reset_runtime_state_for_user_flow",
            )
        self.db.commit()
        for session in sessions:
            _log_session_node(
                "PERSIST",
                session=session,
                executed_node_id=session.current_node_id,
                next_node_id=None,
                reason="reset_runtime_state_for_user_flow",
            )
        return len(sessions), session_ids

    def safe_update_current_node(self, session: FlowSession, next_node_id, reason: str, graph_context: dict[str, Any] | None = None) -> str | None:
        current_status = str(getattr(session, "status", "") or "").lower()
        previous_node_id = getattr(session, "current_node_id", None)
        safe_next_node_id = str(next_node_id) if next_node_id else None
        reason_slug = str(reason or "").strip().lower()
        _log_session_node(
            "BEFORE",
            session=session,
            executed_node_id=(graph_context or {}).get("executed_node_id"),
            next_node_id=safe_next_node_id,
            status=current_status,
            reason=f"safe_update_current_node:{reason_slug}",
        )
        print(
            "[SESSION CURRENT_NODE BEFORE UPDATE] "
            f"session_id={getattr(session, 'id', None)} previous_current_node_id={previous_node_id} "
            f"requested_current_node_id={safe_next_node_id} reason={reason_slug} graph_context={graph_context or {}}"
        )
        if (
            safe_next_node_id is None
            and current_status in {"running", "active"}
            and previous_node_id
            and reason_slug not in ALLOWED_NULL_CURRENT_NODE_REASONS
        ):
            print(
                "[SESSION CURRENT_NODE_NULL_OVERWRITE_BLOCKED] "
                f"session_id={getattr(session, 'id', None)} previous_current_node_id={previous_node_id} reason={reason_slug}"
            )
            safe_next_node_id = str(previous_node_id)
        print(
            "[SESSION CURRENT_NODE AFTER UPDATE] "
            f"session_id={getattr(session, 'id', None)} current_node_id={safe_next_node_id} reason={reason_slug}"
        )
        _log_session_node(
            "AFTER",
            session=session,
            current_node_id=safe_next_node_id,
            executed_node_id=(graph_context or {}).get("executed_node_id"),
            next_node_id=safe_next_node_id,
            status=current_status,
            reason=f"safe_update_current_node:{reason_slug}",
        )
        set_current_node_write_reason(session, reason_slug)
        return safe_next_node_id

    def end_session(
        self,
        session: FlowSession,
        *,
        status: str,
        ended_at: datetime | None = None,
    ) -> FlowSession:
        normalized_status = (status or "").lower()
        print(
            "[SESSION FINALIZE CALL] "
            f"session_id={getattr(session, 'id', None)} "
            f"requested_status={status} current_status={getattr(session, 'status', None)} "
            f"current_node_id={getattr(session, 'current_node_id', None)}"
        )
        print(f"[SESSION FINALIZE REASON] normalized_status={normalized_status}")
        print("[SESSION FINALIZE STACK] " + " | ".join(traceback.format_stack(limit=12)))
        if normalized_status not in FINAL_COMPLETION_STATUSES:
            raise ValueError(f"Invalid status '{status}'")

        if (session.status or "").lower() in FINAL_SESSION_STATUSES:
            print(
                "[SESSION FINALIZE REASON] "
                f"session_id={getattr(session, 'id', None)} already_final_status={session.status}"
            )
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
