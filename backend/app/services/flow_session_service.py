from __future__ import annotations

from app.models.flow_session import FlowSession


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

    def update_session(self, session: FlowSession, node_id: str | None, context: dict | None = None, status: str | None = None) -> None:
        session.current_node_id = node_id

        if context is not None:
            session.context = context

        if status:
            session.status = status

        self.db.commit()
        self.db.refresh(session)
