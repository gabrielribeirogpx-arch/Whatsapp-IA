from __future__ import annotations

from app.models.flow_event import FlowEvent


class FlowEventService:
    def __init__(self, db):
        self.db = db

    def log(self, flow_id, conversation_id, event_type, node_id=None, data=None):
        event = FlowEvent(
            flow_id=flow_id,
            conversation_id=conversation_id,
            node_id=node_id,
            event_type=event_type,
            data=data or {},
        )
        self.db.add(event)
        self.db.commit()
