from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.conversation import Conversation
from app.models.flow import Flow
from app.models.flow_session import FlowSession

SESSION_TTL_MINUTES = 30
FINAL_SESSION_STATUSES = {"finished", "expired", "cancelled"}


class FlowSessionService:
    def __init__(self, db):
        self.db = db

    def get_or_create_session(self, flow_id: str, conversation_id: str) -> FlowSession:
        session = self.db.query(FlowSession).filter_by(
            flow_id=flow_id,
            conversation_id=conversation_id,
        ).first()

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

        if session.variables.get("flow_version") != flow.version:
            print(
                f"[SESSION INVALID] reason=version_mismatch session_version={session.variables.get('flow_version')} flow_version={flow.version}"
            )
            return session, "version_mismatch"

        return session, None

    def save_runtime_session(self, *, tenant_id, user_identifier: str, flow: Flow, current_node_id, status: str = "running", context: dict[str, Any] | None = None) -> FlowSession:
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
        if not session:
            session = FlowSession(
                tenant_id=tenant_id,
                user_identifier=user_identifier,
                flow_id=flow.id,
                current_node_id=str(current_node_id) if current_node_id else None,
                status=status,
                context=context or {},
                variables={"flow_version": flow.version},
            )
            self.db.add(session)
        else:
            session.current_node_id = str(current_node_id) if current_node_id else None
            session.status = status
            session.context = context if context is not None else (session.context or {})
            variables = dict(session.variables or {})
            variables["flow_version"] = flow.version
            session.variables = variables
        self.db.commit()
        self.db.refresh(session)
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
        self.db.commit()
        print(f"[SESSION RESET] reason={reason} tenant_id={tenant_id} user={user_identifier} count={len(sessions)}")

    def update_session(self, session: FlowSession, node_id: str | None, context: dict | None = None, status: str | None = None) -> None:
        session.current_node_id = node_id

        if context is not None:
            session.context = context

        if status:
            session.status = status

        self.db.commit()
        self.db.refresh(session)
