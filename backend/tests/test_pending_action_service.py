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


def test_detect_pending_action_decision_values():
    from app.services.pending_action_service import detect_pending_action_decision

    assert detect_pending_action_decision("sim") == "confirm"
    assert detect_pending_action_decision("não") == "cancel"
    assert detect_pending_action_decision("talvez") == "unknown"


def test_format_pending_calendar_create_conflict_message_variants():
    from app.services.pending_action_service import format_pending_calendar_create_conflict_message

    base = {"summary": "Teste Final", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo"}
    assert "• Reunião Online" in format_pending_calendar_create_conflict_message({**base, "conflicting_events": [{"summary": "Reunião Online"}]})
    assert "• Título" in format_pending_calendar_create_conflict_message({**base, "conflicting_events": [{"title": "Título"}]})
    assert "• Nome" in format_pending_calendar_create_conflict_message({**base, "conflicting_events": [{"name": "Nome"}]})
    assert "Já existem 3 compromissos" in format_pending_calendar_create_conflict_message({**base, "conflicting_events": [{"summary": "Café"}, {"title": "Reunião Online"}, {"name": "Teste Wazza"}]})
    assert "• compromisso" in format_pending_calendar_create_conflict_message({**base, "conflicting_events": [{"id": "x"}]})
    assert format_pending_calendar_create_conflict_message({**base, "conflicting_events": []}) == 'Você já possui um compromisso nesse horário. Deseja criar "Teste Final" mesmo assim?'


def test_pending_action_handler_registry_found_and_missing():
    from types import SimpleNamespace
    from app.services.pending_action_service import PendingActionHandlerRegistry

    registry = PendingActionHandlerRegistry()
    pending = SimpleNamespace(id="p1", action_type="X", payload_json={})
    assert registry.handle(tenant_id="t", conversation_id="c", pending_action=pending, user_message="sim", context={"decision": "confirm"}).startswith("Não consegui")
    registry.register(action_type="X", handler=lambda **kwargs: "ok")
    assert registry.handle(tenant_id="t", conversation_id="c", pending_action=pending, user_message="sim", context={"decision": "confirm"}) == "ok"
