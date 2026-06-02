from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.services import flow_engine_service


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _ExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _ScalarResult(self.value)


class _FakeDB:
    def __init__(self, conversation):
        self.conversation = conversation
        self.added = []
        self.commits = 0

    def execute(self, _statement):
        return _ExecuteResult(self.conversation)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _SessionService:
    def __init__(self, _db, runtime_session):
        self.runtime_session = runtime_session

    def get_runtime_session_state(self, **_kwargs):
        return {
            "session": self.runtime_session,
            "exists": True,
            "status": self.runtime_session.status,
            "is_active": True,
            "is_finalized": False,
        }


def test_process_flow_engine_does_not_reopen_session_finalized_during_continuation(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    condition_node_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number="5511999990001",
        context={},
        retries=0,
        current_node_id=None,
        mode="bot",
        current_flow=None,
    )
    runtime_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="running",
        current_node_id=condition_node_id,
        variables={"current_node_id": str(condition_node_id)},
        flow_version_id=flow_version_id,
    )
    db = _FakeDB(conversation)
    flow = SimpleNamespace(id=flow_id, published_version_id=flow_version_id)
    runtime_graph = {"nodes": [{"id": str(condition_node_id), "type": "condition"}], "edges": []}

    monkeypatch.setattr(flow_engine_service, "FlowSessionService", lambda _db: _SessionService(_db, runtime_session))
    monkeypatch.setattr(flow_engine_service, "get_active_visual_flow", lambda **_kwargs: flow)
    monkeypatch.setattr(flow_engine_service, "is_flow_trigger", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(flow_engine_service, "_get_current_flow_runtime", lambda **_kwargs: runtime_graph)
    monkeypatch.setattr(flow_engine_service, "_get_node", lambda **_kwargs: {"id": str(condition_node_id), "type": "condition"})

    def _finalizing_run_until_wait_node(**_kwargs):
        runtime_session.status = "completed"
        runtime_session.current_node_id = None
        return None

    monkeypatch.setattr(flow_engine_service, "run_until_wait_node", _finalizing_run_until_wait_node)

    flow_engine_service.process_flow_engine(
        db=db,
        tenant_id=tenant_id,
        phone="5511999990001",
        message_text="suporte",
    )

    assert runtime_session.status == "completed"
    assert runtime_session.current_node_id is None
    assert db.commits == 1
