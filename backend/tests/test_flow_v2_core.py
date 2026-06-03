from __future__ import annotations

import uuid

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash


class _FakeDB:
    def flush(self):
        pass


class _FakeSession:
    def __init__(self, tenant_id, flow_version_id):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.flow_version_id = flow_version_id
        self.current_node_id = "start"
        self.status = FlowV2SessionStatus.RUNNING
        self.last_event_index = 0


class _FakeSnapshotRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.loaded_with = None

    def load(self, db, *, tenant_id, flow_version_id):
        self.loaded_with = {"tenant_id": tenant_id, "flow_version_id": flow_version_id}
        return self.snapshot


class _FakeEventStore:
    def __init__(self):
        self.events = []

    def append(self, db, *, session, event_type, payload=None, node_id=None, input_message_id=None):
        session.last_event_index += 1
        self.events.append(
            {
                "event_index": session.last_event_index,
                "event_type": str(event_type),
                "payload": payload or {},
                "node_id": node_id,
                "input_message_id": input_message_id,
            }
        )


class _FakeSessionManager:
    def __init__(self, session, event_store):
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db, *, runtime_input, snapshot):
        if self.session.last_event_index == 0:
            self.event_store.append(
                db,
                session=self.session,
                event_type=FlowV2EventType.SESSION_STARTED,
                payload={"snapshot_hash": snapshot.hash, "start_node_id": snapshot.start_node_id},
            )
        return self.session

    def move_to(self, db, *, session, node_id, status):
        session.current_node_id = node_id
        session.status = str(status)


def test_canonical_hash_ignores_embedded_hash_key() -> None:
    snapshot = {"schema_version": 1, "start_node_id": "start", "nodes": [], "edges": []}
    with_hash = {**snapshot, "hash": "client-side-copy"}

    assert canonical_hash(snapshot) == canonical_hash({k: v for k, v in with_hash.items() if k != "hash"})


def test_executor_uses_only_explicit_flow_version_snapshot_and_event_sourcing() -> None:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "data": {"text": "Olá"}}],
        "edges": [],
    }
    snapshot = FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash=canonical_hash(raw_snapshot),
        nodes=tuple(raw_snapshot["nodes"]),
        edges=tuple(raw_snapshot["edges"]),
        start_node_id="start",
    )
    event_store = _FakeEventStore()
    session = _FakeSession(tenant_id, flow_version_id)
    snapshot_repo = _FakeSnapshotRepository(snapshot)
    executor = FlowV2Executor(
        snapshot_repository=snapshot_repo,
        event_store=event_store,
        session_manager=_FakeSessionManager(session, event_store),
    )

    output = executor.handle_input(
        _FakeDB(),
        RuntimeInput(
            tenant_id=tenant_id,
            flow_version_id=flow_version_id,
            external_user_id="whatsapp:+5511999999999",
            message_text="oi",
            input_message_id="wamid.1",
        ),
    )

    assert snapshot_repo.loaded_with == {"tenant_id": tenant_id, "flow_version_id": flow_version_id}
    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Olá"},)
    assert [event["event_type"] for event in event_store.events] == [
        "session.started",
        "input.received",
        "node.entered",
        "output.emitted",
        "node.completed",
        "session.completed",
    ]
