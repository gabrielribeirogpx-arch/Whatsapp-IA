from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.workers import message_worker


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class _FakeDB:
    def __init__(self):
        self.messages = []
        self.committed = 0

    def add(self, obj):
        if getattr(obj, "text", None) is not None:
            self.messages.append(obj)

    def flush(self):
        return None

    def refresh(self, _):
        return None

    def execute(self, _):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.messages[-1]))

    def commit(self):
        self.committed += 1

    def rollback(self):
        return None

    def close(self):
        return None

    def in_transaction(self):
        return False


def test_webhook_flow_e2e(monkeypatch):
    print("[WEBHOOK FLOW E2E TEST START]")
    sent = []
    sessions = {}

    condition_node_id = "127bcf3a-0064-4fce-86b0-5721ba6188e2"

    def _run_two_messages_for_tenant(tenant_id: str, phone_number_id: str, branch_text: str):
        db = _FakeDB()
        class _ConversationGuard(SimpleNamespace):
            def __setattr__(self, name, value):
                if name == "current_node_id" and value:
                    raise AssertionError("versioned/runtime node id must not be persisted in conversations.current_node_id")
                super().__setattr__(name, value)

        conversation = _ConversationGuard(
            id=f"conv-{tenant_id}",
            tenant_id=tenant_id,
            phone_number="5511999990001",
            mode="bot",
            current_node_id=None,
            context={},
            conversation_state=None,
        )

        tenant = SimpleNamespace(id=tenant_id)
        contact = SimpleNamespace(id=f"ct-{tenant_id}", phone="5511999990001")

        monkeypatch.setattr(message_worker, "get_redis_client", lambda: _FakeRedis())
        monkeypatch.setattr(message_worker, "SessionLocal", lambda: db)
        monkeypatch.setattr(message_worker, "resolve_tenant_by_phone_number_id", lambda _db, _pnid: tenant if _pnid == phone_number_id else None)
        monkeypatch.setattr(message_worker, "register_processed_message", lambda **kwargs: True)
        monkeypatch.setattr(message_worker, "upsert_contact_for_phone", lambda *args, **kwargs: contact)
        monkeypatch.setattr(message_worker, "ensure_conversation_contact_link", lambda *args, **kwargs: None)
        monkeypatch.setattr(message_worker, "get_or_create_conversation", lambda *args, **kwargs: (conversation, False))
        monkeypatch.setattr(message_worker, "normalize_meta_message", lambda payload: [{"phone": "5511999990001", "text": payload["text"], "message_id": payload["message_id"], "name": "Cliente", "phone_number_id": payload["phone_number_id"]}])

        import app.services.message_router as message_router

        class _SessionService:
            def __init__(self, _db):
                pass

            def get_runtime_session_state(self, tenant_id, phone, flow_id):
                s = sessions.get((tenant_id, phone))
                return {"session": s, "exists": bool(s), "status": (s.status if s else ""), "is_active": bool(s and s.current_node_id), "is_finalized": bool(s and s.status == "completed")}

        monkeypatch.setattr(message_router, "FlowSessionService", _SessionService)
        monkeypatch.setattr(message_router, "get_active_visual_flow", lambda **kwargs: SimpleNamespace(id=f"flow-{tenant_id}"))
        monkeypatch.setattr(message_router, "_resolve_triggered_flow", lambda **kwargs: SimpleNamespace(id=f"flow-{tenant_id}"))
        monkeypatch.setattr(message_router, "is_flow_trigger", lambda *args, **kwargs: True)
        monkeypatch.setattr(message_router, "log_conversation_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(message_router, "handle_bot", lambda *args, **kwargs: {"response": "fallback"})

        called_session_nodes = []
        runtime_graph_sources = []
        runtime_flow_versions = []

        def _fake_flow_engine(*, db, message, conversation, session_node_id=None):
            runtime_graph_sources.append("published_version")
            runtime_flow_versions.append("v-1")
            called_session_nodes.append(session_node_id)
            key = (conversation.tenant_id, conversation.phone_number)
            text = (message.text or "").lower()
            state = sessions.get(key)
            if not state:
                sessions[key] = SimpleNamespace(current_node_id=condition_node_id, status="running", variables={"current_node_id": condition_node_id})
                sent.append((conversation.tenant_id, "Olá!"))
                return {"response": "Olá!"}
            print(f"[CONDITION EVALUATED] condition_node_id={condition_node_id} incoming_text=suporte matched=true branch=true")
            if "suporte" in text:
                sent.append((conversation.tenant_id, "Resposta A"))
                state.current_node_id = None
                state.status = "completed"
                return {"response": "Resposta A"}
            return {"response": "Resposta B"}

        monkeypatch.setattr(message_router, "handle_visual_flow_priority", _fake_flow_engine)

        message_worker.process_incoming_message({"phone_number_id": phone_number_id, "text": "oi", "message_id": f"{tenant_id}-1"})
        assert sent[-1][1] == "Olá!"
        assert sessions[(tenant_id, "5511999990001")].current_node_id == condition_node_id
        assert runtime_graph_sources[-1] == "published_version"
        assert conversation.current_node_id is None

        message_worker.process_incoming_message({"phone_number_id": phone_number_id, "text": branch_text, "message_id": f"{tenant_id}-2"})
        assert conversation.context.get("flow_current_node_id") == condition_node_id
        assert runtime_flow_versions[-1] == runtime_flow_versions[0]
        assert called_session_nodes[-1] == condition_node_id
        assert sent[-1][1] == "Resposta A"
        assert sessions[(tenant_id, "5511999990001")].status == "completed"

    _run_two_messages_for_tenant("tenant-A", "pnid-A", "suporte")
    _run_two_messages_for_tenant("tenant-B", "pnid-B", "suporte")
    assert [item[0] for item in sent] == ["tenant-A", "tenant-A", "tenant-B", "tenant-B"]
    print("[WEBHOOK FLOW E2E TEST PASS]")
