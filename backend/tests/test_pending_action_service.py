from datetime import datetime, timedelta
import uuid

from app.services.pending_action_service import CALENDAR_CREATE_CONFIRMATION, PendingActionService


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        for item in reversed(self.db.rows):
            if item.consumed_at is None:
                return item
        return None

    def delete(self, synchronize_session=False):
        count = len(self.db.rows)
        self.db.rows.clear()
        return count


class FakeDb:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        pass

    def delete(self, row):
        self.rows.remove(row)

    def query(self, model):
        return FakeQuery(self)


def test_pending_action_save_get_consume_cancel_and_expire():
    db = FakeDb()
    service = PendingActionService(db)
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    pending = service.save_pending_action(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        action_type=CALENDAR_CREATE_CONFIRMATION,
        payload={"summary": "Call"},
    )

    assert pending is not None
    assert service.get_pending_action(tenant_id=tenant_id, conversation_id=conversation_id).payload_json["summary"] == "Call"
    assert service.consume_pending_action(tenant_id=tenant_id, conversation_id=conversation_id, pending_id=pending.id) is True
    assert service.get_pending_action(tenant_id=tenant_id, conversation_id=conversation_id) is None

    pending = service.save_pending_action(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        action_type=CALENDAR_CREATE_CONFIRMATION,
        payload={"summary": "Call"},
    )
    assert service.cancel_pending_action(tenant_id=tenant_id, conversation_id=conversation_id, pending_id=pending.id) is True
    assert service.get_pending_action(tenant_id=tenant_id, conversation_id=conversation_id) is None

    expired = service.save_pending_action(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        action_type=CALENDAR_CREATE_CONFIRMATION,
        payload={"summary": "Old"},
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    assert expired is not None
    assert service.get_pending_action(tenant_id=tenant_id, conversation_id=conversation_id) is None
