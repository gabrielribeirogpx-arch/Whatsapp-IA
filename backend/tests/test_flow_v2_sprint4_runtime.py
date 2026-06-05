from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.flow_v2.actions import ScheduleDelayAction, SendMessageAction
from app.flow_v2.channel_adapter import WhatsAppAdapter
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.publish_service import FlowV2PublishService
from app.flow_v2.runtime_worker import FlowV2RuntimeWorker
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash
from app.models.flow import FlowVersion


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, item):
        if isinstance(item, FlowVersion) and item.id is None:
            item.id = uuid.uuid4()
        self.added.append(item)

    def flush(self):
        pass


class _FakeSession:
    def __init__(self, tenant_id, flow_version_id, current_node_id="start"):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.flow_version_id = flow_version_id
        self.current_node_id = current_node_id
        self.status = FlowV2SessionStatus.RUNNING
        self.last_event_index = 0
        self.external_user_id = "whatsapp:+5511999999999"
        self.contact_id = None
        self.conversation_id = None


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
        self.events.append({"event_type": str(event_type), "payload": payload or {}, "node_id": node_id})


class _FakeSessionManager:
    def __init__(self, session, event_store):
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db, *, runtime_input, snapshot):
        if self.session.last_event_index == 0:
            self.event_store.append(db, session=self.session, event_type=FlowV2EventType.SESSION_STARTED)
        return self.session

    def move_to(self, db, *, session, node_id, status):
        session.current_node_id = node_id
        session.status = str(status)


def _snapshot(raw_snapshot, tenant_id=None, flow_version_id=None):
    tenant_id = tenant_id or uuid.uuid4()
    flow_version_id = flow_version_id or uuid.uuid4()
    return FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash=canonical_hash(raw_snapshot),
        nodes=tuple(raw_snapshot["nodes"]),
        edges=tuple(raw_snapshot["edges"]),
        start_node_id=raw_snapshot["start_node_id"],
    )


def _executor(raw_snapshot):
    snapshot = _snapshot(raw_snapshot)
    event_store = _FakeEventStore()
    session = _FakeSession(snapshot.tenant_id, snapshot.flow_version_id)
    executor = FlowV2Executor(
        snapshot_repository=_FakeSnapshotRepository(snapshot),
        event_store=event_store,
        session_manager=_FakeSessionManager(session, event_store),
    )
    return executor, snapshot, event_store, session, _FakeDB()


def _input(snapshot, metadata=None, conversation_id=None, contact_id=None):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        conversation_id=conversation_id,
        contact_id=contact_id,
        metadata=metadata or {},
    )


def test_runtime_generates_send_message_action() -> None:
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )

    output = executor.handle_input(db, _input(snapshot))

    assert isinstance(output.actions[0], SendMessageAction)
    assert output.actions[0].text == "Olá"
    assert output.effects == ({"type": "send_message", "text": "Olá"},)


def test_whatsapp_adapter_receives_action_from_runtime_worker() -> None:
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )
    adapter = WhatsAppAdapter()

    result = FlowV2RuntimeWorker(executor=executor, channel_adapter=adapter).process(db, _input(snapshot))

    assert adapter.sent_actions == list(result.actions)
    assert result.deliveries[0]["status"] == "mocked"
    assert result.deliveries[0]["text"] == "Olá"



def test_message_action_preserves_runtime_metadata_and_never_empty_tenant_id() -> None:
    provider_id = str(uuid.uuid4())
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )

    output = executor.handle_input(
        db,
        _input(
            snapshot,
            metadata={
                "tenant_id": str(snapshot.tenant_id),
                "provider_id": provider_id,
                "flow_id": "flow-1",
                "source": "message_worker",
            },
        ),
    )

    action = output.actions[0]
    assert isinstance(action, SendMessageAction)
    assert str(action.tenant_id) == str(snapshot.tenant_id)
    assert action.metadata["tenant_id"] == str(snapshot.tenant_id)
    assert action.metadata["provider_id"] == provider_id
    assert action.metadata["flow_id"] == "flow-1"
    assert action.metadata["source"] == "message_worker"
    assert action.metadata["node_id"] == "start"
    assert action.metadata["tenant_id"] != ""


def test_whatsapp_adapter_propagates_structured_ids_to_client() -> None:
    provider_id = str(uuid.uuid4())
    conversation_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    executor, snapshot, _, session, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )
    calls = []

    def client(**kwargs):
        calls.append(kwargs)
        return {"status": "queued", **kwargs}

    adapter = WhatsAppAdapter(client=client)

    FlowV2RuntimeWorker(executor=executor, channel_adapter=adapter).process(
        db,
        _input(
            snapshot,
            conversation_id=conversation_id,
            contact_id=contact_id,
            metadata={"tenant_id": str(snapshot.tenant_id), "provider_id": provider_id},
        ),
    )

    assert calls[0]["tenant_id"] == snapshot.tenant_id
    assert calls[0]["session_id"] == session.id
    assert calls[0]["conversation_id"] == conversation_id
    assert calls[0]["contact_id"] == contact_id
    assert calls[0]["metadata"]["tenant_id"] == str(snapshot.tenant_id)
    assert calls[0]["metadata"]["provider_id"] == provider_id
    assert calls[0]["metadata"]["tenant_id"] != ""

def test_delay_worker_resumes_due_job_and_emits_delay_resumed() -> None:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    session = _FakeSession(tenant_id, flow_version_id, current_node_id="after_delay")
    job = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, session_id=session.id, resume_node_id="after_delay", run_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1))

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def __iter__(self):
            return iter(self.value)

        def scalar_one_or_none(self):
            return self.value

    class _DelayDB:
        def __init__(self):
            self.calls = 0
            self.deleted = 0

        def execute(self, statement):
            text = str(statement)
            if "DELETE FROM flow_v2_scheduled_jobs" in text:
                self.deleted += 1
                return _Result(None)
            self.calls += 1
            if self.calls == 1:
                return _Result([job])
            return _Result(session)

        def flush(self):
            pass

    class _RuntimeWorker:
        def __init__(self):
            self.inputs = []

        def process(self, db, runtime_input):
            self.inputs.append(runtime_input)
            return SimpleNamespace(runtime_output=RuntimeOutput(session_id=session.id, status=FlowV2SessionStatus.WAITING, current_node_id="done"), actions=(), deliveries=())

    event_store = _FakeEventStore()
    runtime_worker = _RuntimeWorker()
    result = FlowV2DelayWorker(runtime_worker=runtime_worker, event_store=event_store).run_due(_DelayDB(), now=datetime.now(UTC).replace(tzinfo=None))

    assert result.processed == 1
    assert result.resumed_session_ids == (session.id,)
    assert event_store.events[0]["event_type"] == "DELAY_RESUMED"
    assert runtime_worker.inputs[0].metadata["event_type"] == "DELAY_RESUMED"


def test_publish_service_creates_new_version_and_updates_active_version_id() -> None:
    tenant_id = uuid.uuid4()
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        nodes_json=[{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
        edges_json=[{"id": "e1", "source": "start", "target": "end"}],
        nodes=None,
        edges=None,
        current_version_id=None,
        published_version_id=None,
        active_version_id=None,
        status="draft",
    )

    class _Scalar:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def scalar_one_or_none(self):
            return self.value

    class _PublishDB(_FakeDB):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def in_transaction(self):
            return True

        def execute(self, statement):
            if "UPDATE flow_versions" in str(statement):
                return _Scalar(None)
            self.calls += 1
            return _Scalar(flow if self.calls == 1 else 2)

    db = _PublishDB()

    result = FlowV2PublishService().publish_draft(db, tenant_id=tenant_id, flow_id=flow.id)

    assert result.version.version == 3
    assert result.version.is_published is True
    assert flow.active_version_id == result.version.id
    assert flow.published_version_id == result.version.id
    assert flow.current_version_id == result.version.id


def test_runtime_executes_published_version_id() -> None:
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [{"id": "start", "type": "message", "content": "Publicado"}, {"id": "end", "type": "message"}],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )

    FlowV2RuntimeWorker(executor=executor).process(db, _input(snapshot))

    assert executor.snapshot_repository.loaded_with == {"tenant_id": snapshot.tenant_id, "flow_version_id": snapshot.flow_version_id}
