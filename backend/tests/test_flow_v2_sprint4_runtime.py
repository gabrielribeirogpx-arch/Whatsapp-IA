from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.flow_v2.actions import ScheduleDelayAction, SendMediaAction, SendMessageAction
from app.flow_v2.channel_adapter import WhatsAppAdapter
from app.flow_v2.contracts import (
    FlowV2EventType,
    FlowV2SessionStatus,
    RuntimeInput,
    RuntimeOutput,
)
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.publish_service import FlowV2PublishService
from app.flow_v2.publisher import FlowV2Publisher
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
        self.context = {}


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

    def append(
        self,
        db,
        *,
        session,
        event_type,
        payload=None,
        node_id=None,
        input_message_id=None,
    ):
        session.last_event_index += 1
        self.events.append(
            {
                "event_type": str(event_type),
                "payload": payload or {},
                "node_id": node_id,
            }
        )


class _FakeSessionManager:
    def __init__(self, session, event_store):
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db, *, runtime_input, snapshot):
        if self.session.last_event_index == 0:
            self.event_store.append(
                db, session=self.session, event_type=FlowV2EventType.SESSION_STARTED
            )
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
    session = _FakeSession(
        snapshot.tenant_id,
        snapshot.flow_version_id,
        current_node_id=snapshot.start_node_id,
    )
    executor = FlowV2Executor(
        snapshot_repository=_FakeSnapshotRepository(snapshot),
        event_store=event_store,
        session_manager=_FakeSessionManager(session, event_store),
    )
    return executor, snapshot, event_store, session, _FakeDB()


def _input(
    snapshot, metadata=None, conversation_id=None, contact_id=None, message_text="oi"
):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text=message_text,
        conversation_id=conversation_id,
        contact_id=contact_id,
        metadata=metadata or {},
    )


def test_condition_builder_keywords_contains_routes_positive_and_logs_payload(
    caplog,
) -> None:
    condition_node = {
        "id": "condition",
        "type": "condition",
        "data": {
            "keywords": ["suporte"],
            "matchType": "contains",
        },
    }
    executor, snapshot, event_store, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "condition",
            "nodes": [
                condition_node,
                {"id": "positive", "type": "message", "content": "Ramo positivo"},
                {"id": "negative", "type": "message", "content": "Ramo negativo"},
            ],
            "edges": [
                {
                    "id": "e-true",
                    "source": "condition",
                    "sourceHandle": "true",
                    "target": "positive",
                },
                {
                    "id": "e-false",
                    "source": "condition",
                    "sourceHandle": "false",
                    "target": "negative",
                },
            ],
        }
    )

    with caplog.at_level(logging.INFO, logger="app.flow_v2.node_executors"):
        output = executor.handle_input(db, _input(snapshot, message_text="suporte"))

    condition_event = next(
        event
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.CONDITION_EVALUATED)
    )
    assert condition_event["payload"] == {
        "node_id": "condition",
        "conditions": [],
        "message": "suporte",
        "keywords": ["suporte"],
        "match_type": "contains",
        "result": True,
        "source_handle": "true",
        "target_node_id": "positive",
    }
    assert output.effects == ({"type": "send_message", "text": "Ramo positivo"},)
    assert (
        "[V2 CONDITION SNAPSHOT NODE] node_id=condition node={'id': 'condition', 'type': 'condition', 'data': {'keywords': ['suporte'], 'matchType': 'contains'}}"
        in caplog.text
    )
    assert (
        "[V2 CONDITION] node_id=condition message=suporte keywords=['suporte'] match_type=contains result=True source_handle=true target_node_id=positive"
        in caplog.text
    )


def test_condition_builder_keywords_contains_routes_negative_for_klm(caplog) -> None:
    condition_node = {
        "id": "condition",
        "type": "condition",
        "data": {
            "keywords": ["suporte"],
            "matchType": "contains",
        },
    }
    executor, snapshot, event_store, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "condition",
            "nodes": [
                condition_node,
                {"id": "positive", "type": "message", "content": "Ramo positivo"},
                {"id": "negative", "type": "message", "content": "Ramo negativo"},
            ],
            "edges": [
                {
                    "id": "e-true",
                    "source": "condition",
                    "sourceHandle": "true",
                    "target": "positive",
                },
                {
                    "id": "e-false",
                    "source": "condition",
                    "sourceHandle": "false",
                    "target": "negative",
                },
            ],
        }
    )

    with caplog.at_level(logging.INFO, logger="app.flow_v2.node_executors"):
        output = executor.handle_input(db, _input(snapshot, message_text="klm"))

    condition_event = next(
        event
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.CONDITION_EVALUATED)
    )
    assert condition_event["payload"] == {
        "node_id": "condition",
        "conditions": [],
        "message": "klm",
        "keywords": ["suporte"],
        "match_type": "contains",
        "result": False,
        "source_handle": "false",
        "target_node_id": "negative",
    }
    assert output.effects == ({"type": "send_message", "text": "Ramo negativo"},)
    assert (
        "[V2 CONDITION SNAPSHOT NODE] node_id=condition node={'id': 'condition', 'type': 'condition', 'data': {'keywords': ['suporte'], 'matchType': 'contains'}}"
        in caplog.text
    )
    assert (
        "[V2 CONDITION] node_id=condition message=klm keywords=['suporte'] match_type=contains result=False source_handle=false target_node_id=negative"
        in caplog.text
    )


def test_condition_not_equals_executes_only_true_classification_branch() -> None:
    executor, snapshot, event_store, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "condition",
            "nodes": [
                {
                    "id": "condition",
                    "type": "condition",
                    "data": {
                        "conditions": [
                            {
                                "field": "ai.classification",
                                "operator": "!=",
                                "value": "outro",
                            }
                        ]
                    },
                },
                {"id": "choice", "type": "message", "content": "Escolha uma opção"},
                {
                    "id": "fallback",
                    "type": "message",
                    "content": "Não consegui identificar...",
                },
            ],
            "edges": [
                {
                    "id": "e-true",
                    "source": "condition",
                    "sourceHandle": "true",
                    "target": "choice",
                },
                {
                    "id": "e-false",
                    "source": "condition",
                    "sourceHandle": "false",
                    "target": "fallback",
                },
            ],
        }
    )

    output = executor.handle_input(
        db,
        _input(
            snapshot,
            metadata={"ai": {"classification": {"category": "Limpeza"}}},
        ),
    )

    assert output.effects == ({"type": "send_message", "text": "Escolha uma opção"},)
    transitions = [
        event["payload"]
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.TRANSITION_SELECTED)
        and event["node_id"] == "condition"
    ]
    assert transitions == [{"source_handle": "true", "target_node_id": "choice"}]


def test_condition_reads_intent_category_persisted_in_session_and_traces_route(caplog) -> None:
    executor, snapshot, event_store, session, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "condition",
            "nodes": [
                {
                    "id": "condition",
                    "type": "condition",
                    "data": {
                        "conditions": [
                            {"field": "intent_category", "operator": "!=", "value": "outro"}
                        ]
                    },
                },
                {"id": "true-message", "type": "message", "content": "Ramo true"},
                {"id": "false-message", "type": "message", "content": "Ramo false"},
            ],
            "edges": [
                {"id": "condition-true", "source": "condition", "sourceHandle": "true", "target": "true-message"},
                {"id": "condition-false", "source": "condition", "sourceHandle": "false", "target": "false-message"},
            ],
        }
    )
    session.context = {"intent_category": "Implante"}

    with caplog.at_level(logging.INFO):
        output = executor.handle_input(db, _input(snapshot, metadata={}))

    assert output.effects == ({"type": "send_message", "text": "Ramo true"},)
    condition_event = next(
        event for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.CONDITION_EVALUATED)
    )
    assert condition_event["payload"] == {
        "node_id": "condition",
        "conditions": [{"field": "intent_category", "operator": "!=", "value": "outro"}],
        "message": "oi",
        "keywords": [],
        "match_type": "equals",
        "result": True,
        "source_handle": "true",
        "target_node_id": "true-message",
    }
    assert "intent_category='Implante'" in caplog.text
    assert "selected_source_handle=true next_transition_id=condition-true next_node_id=true-message" in caplog.text


def test_ai_classification_condition_enqueues_and_executes_only_true_message(
    monkeypatch, caplog
) -> None:
    """A true Condition decision must never fall through to its false sibling."""
    executor, snapshot, event_store, session, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "classification",
            "nodes": [
                {
                    "id": "classification",
                    "type": "ai_classification",
                    "data": {
                        "input_template": "{{last_message}}",
                        "categories": ["Aparelho", "Limpeza"],
                        "output_variable": "intent_category",
                    },
                },
                {
                    "id": "condition",
                    "type": "condition",
                    "data": {"conditions": [{"field": "intent_category", "operator": "equals", "value": "Aparelho"}]},
                },
                {"id": "message-true", "type": "message", "content": "Ramo True"},
                {"id": "message-false", "type": "message", "content": "Ramo False"},
            ],
            "edges": [
                {"id": "classification-condition", "source": "classification", "target": "condition"},
                {"id": "condition-true", "source": "condition", "sourceHandle": "true", "target": "message-true"},
                {"id": "condition-false", "source": "condition", "sourceHandle": "false", "target": "message-false"},
            ],
        }
    )
    adapter = WhatsAppAdapter()
    monkeypatch.setattr("app.flow_v2.executors._legacy.resolve_ai_config", lambda *_args: {})
    monkeypatch.setattr(
        "app.flow_v2.executors._legacy.classify_for_tenant",
        lambda *_args, **_kwargs: {"category": "Aparelho", "confidence": 0.99},
    )
    monkeypatch.setattr("app.flow_v2.executors._legacy.record_ai_execution", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.flow_v2.executors._legacy.get_flow_id", lambda *_args, **_kwargs: "flow-1")

    with caplog.at_level(logging.INFO):
        result = FlowV2RuntimeWorker(executor=executor, channel_adapter=adapter).process(
            db, _input(snapshot, message_text="Quero um aparelho")
        )

    condition_transitions = [
        event["payload"]
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.TRANSITION_SELECTED)
        and event["node_id"] == "condition"
    ]
    entered_messages = [
        event["node_id"]
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.NODE_ENTERED)
        and event["node_id"] in {"message-true", "message-false"}
    ]

    assert session.variables["intent_category"] == "Aparelho"
    assert condition_transitions == [{"source_handle": "true", "target_node_id": "message-true"}]
    assert entered_messages == ["message-true"]
    assert [action.text for action in result.actions] == ["Ramo True"]
    assert len(adapter.sent_actions) == 1
    assert "Ramo False" not in [action.text for action in adapter.sent_actions]
    assert "selected_source_handle=true queued_transition_count=1" in caplog.text
    assert "queued_next_node_ids=['message-true'] default_transitions_revisited=false" in caplog.text


def test_runtime_generates_send_message_action() -> None:
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [
                {"id": "start", "type": "message", "content": "Olá"},
                {"id": "end", "type": "message"},
            ],
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
            "nodes": [
                {"id": "start", "type": "message", "content": "Olá"},
                {"id": "end", "type": "message"},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )
    adapter = WhatsAppAdapter()

    result = FlowV2RuntimeWorker(executor=executor, channel_adapter=adapter).process(
        db, _input(snapshot)
    )

    assert adapter.sent_actions == list(result.actions)
    assert result.deliveries[0]["status"] == "mocked"
    assert result.deliveries[0]["text"] == "Olá"


def test_message_action_preserves_runtime_metadata_and_never_empty_tenant_id() -> None:
    provider_id = str(uuid.uuid4())
    executor, snapshot, _, _, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "start",
            "nodes": [
                {"id": "start", "type": "message", "content": "Olá"},
                {"id": "end", "type": "message"},
            ],
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
            "nodes": [
                {"id": "start", "type": "message", "content": "Olá"},
                {"id": "end", "type": "message"},
            ],
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



def test_message_delay_message_publish_waits_worker_resumes_and_sends_next_message() -> None:
    nodes = [
        {"id": "start", "type": "message", "content": "Olá"},
        {"id": "delay", "type": "delay", "seconds": 5},
        {"id": "after_delay", "type": "message", "content": "Depois"},
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "delay"},
        {"id": "e2", "source": "delay", "target": "after_delay"},
    ]

    published = FlowV2Publisher().publish(nodes=nodes, edges=edges)
    assert published.validation.is_valid
    executor, snapshot, event_store, session, db = _executor(published.snapshot)

    initial = executor.handle_input(db, _input(snapshot))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "after_delay"
    assert initial.effects == ({"type": "send_message", "text": "Olá"},)
    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert len(scheduled_jobs) == 1
    assert scheduled_jobs[0].resume_node_id == "after_delay"

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def __iter__(self):
            return iter(self.value)

        def scalar_one_or_none(self):
            return self.value

    class _DelayDB(_FakeDB):
        def __init__(self, job):
            super().__init__()
            self.job = job
            self.calls = 0
            self.deleted = 0

        def execute(self, statement):
            if "DELETE FROM flow_v2_scheduled_jobs" in str(statement):
                self.deleted += 1
                return _Result(None)
            self.calls += 1
            if self.calls == 1:
                return _Result([self.job])
            return _Result(session)

    class _RuntimeWorker:
        def __init__(self):
            self.outputs = []

        def process(self, db, runtime_input):
            output = executor.handle_input(db, runtime_input)
            self.outputs.append(output)
            return SimpleNamespace(runtime_output=output, actions=output.actions, deliveries=())

    class _IdempotencyStore:
        def reserve_once(self, db, **kwargs):
            return SimpleNamespace(is_duplicate=False)

        def mark_session(self, db, *, decision, session_id):
            pass

    executor.idempotency_store = _IdempotencyStore()
    runtime_worker = _RuntimeWorker()
    result = FlowV2DelayWorker(
        runtime_worker=runtime_worker,
        event_store=event_store,
    ).run_due(_DelayDB(scheduled_jobs[0]), now=scheduled_jobs[0].run_at + timedelta(seconds=1))

    assert result.processed == 1
    assert runtime_worker.outputs[0].status == FlowV2SessionStatus.COMPLETED
    assert runtime_worker.outputs[0].effects == ({"type": "send_message", "text": "Depois"},)
    assert session.status == str(FlowV2SessionStatus.COMPLETED)
    assert session.current_node_id is None


def test_delay_worker_resumes_due_job_and_emits_delay_resumed() -> None:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    session = _FakeSession(tenant_id, flow_version_id, current_node_id="after_delay")
    job = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        session_id=session.id,
        resume_node_id="after_delay",
        run_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
    )

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
            return SimpleNamespace(
                runtime_output=RuntimeOutput(
                    session_id=session.id,
                    status=FlowV2SessionStatus.WAITING,
                    current_node_id="done",
                ),
                actions=(),
                deliveries=(),
            )

    event_store = _FakeEventStore()
    runtime_worker = _RuntimeWorker()
    result = FlowV2DelayWorker(
        runtime_worker=runtime_worker, event_store=event_store
    ).run_due(_DelayDB(), now=datetime.now(UTC).replace(tzinfo=None))

    assert result.processed == 1
    assert result.resumed_session_ids == (session.id,)
    assert event_store.events[0]["event_type"] == "DELAY_RESUMED"
    assert runtime_worker.inputs[0].metadata["event_type"] == "DELAY_RESUMED"


def test_publish_service_creates_new_version_and_updates_active_version_id() -> None:
    tenant_id = uuid.uuid4()
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        nodes_json=[
            {"id": "start", "type": "message", "content": "Olá"},
            {"id": "end", "type": "message"},
        ],
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

    result = FlowV2PublishService().publish_draft(
        db, tenant_id=tenant_id, flow_id=flow.id
    )

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
            "nodes": [
                {"id": "start", "type": "message", "content": "Publicado"},
                {"id": "end", "type": "message"},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }
    )

    FlowV2RuntimeWorker(executor=executor).process(db, _input(snapshot))

    assert executor.snapshot_repository.loaded_with == {
        "tenant_id": snapshot.tenant_id,
        "flow_version_id": snapshot.flow_version_id,
    }


def test_media_image_node_generates_action_and_continues_to_message() -> None:
    executor, snapshot, event_store, session, db = _executor({"schema_version": 1, "start_node_id": "media", "nodes": [{"id": "media", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "https://cdn.example.com/foto.jpg", "caption": "Veja a imagem"}}, {"id": "next", "type": "message", "content": "Depois da mídia"}], "edges": [{"id": "e1", "source": "media", "target": "next"}]})
    output = executor.handle_input(db, _input(snapshot))
    assert output.status == FlowV2SessionStatus.COMPLETED
    assert len(output.actions) == 2
    assert output.actions[0].action_type == "send_media"
    assert output.actions[0].as_effect()["media_type"] == "image"
    assert output.actions[0].as_effect()["media_url"] == "https://cdn.example.com/foto.jpg"
    assert output.actions[1].action_type == "send_message"
    assert session.current_node_id is None


def test_media_document_node_generates_document_action() -> None:
    executor, snapshot, _, _, db = _executor({"schema_version": 1, "start_node_id": "media", "nodes": [{"id": "media", "type": "media", "data": {"isStart": True, "media_type": "document", "media_url": "https://cdn.example.com/contrato.pdf", "caption": "Segue o PDF", "filename": "contrato.pdf"}}], "edges": []})
    output = executor.handle_input(db, _input(snapshot))
    assert output.status == FlowV2SessionStatus.COMPLETED
    effect = output.actions[0].as_effect()
    assert effect["media_type"] == "document"
    assert effect["media_url"] == "https://cdn.example.com/contrato.pdf"
    assert effect["caption"] == "Segue o PDF"
    assert effect["filename"] == "contrato.pdf"


def test_media_invalid_url_fails_session_without_dispatching_action() -> None:
    executor, snapshot, _, session, db = _executor({"schema_version": 1, "start_node_id": "media", "nodes": [{"id": "media", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "http://cdn.example.com/foto.jpg"}}], "edges": []})
    try:
        executor.handle_input(db, _input(snapshot))
    except RuntimeError as exc:
        assert "Invalid media_url" in str(exc)
    else:
        raise AssertionError("expected invalid media_url to raise RuntimeError")
    assert session.status == str(FlowV2SessionStatus.FAILED)


def test_whatsapp_adapter_dispatches_media_actions_to_mock_delivery() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    action = SendMediaAction(tenant_id=tenant_id, session_id=session_id, external_user_id="whatsapp:+5511999999999", media_type="image", media_url="https://cdn.example.com/foto.jpg", caption="Veja")
    delivery = WhatsAppAdapter().dispatch(action)
    assert delivery["status"] == "mocked"
    assert delivery["type"] == "image"
    assert delivery["image_url"] == "https://cdn.example.com/foto.jpg"


def test_media_audio_node_generates_action_without_caption() -> None:
    executor, snapshot, _, _, db = _executor({"schema_version": 1, "start_node_id": "media", "nodes": [{"id": "media", "type": "media", "data": {"isStart": True, "media_type": "audio", "media_url": "https://cdn.example.com/audio.mp3", "caption": "Ignorar"}}], "edges": []})
    output = executor.handle_input(db, _input(snapshot))
    assert output.status == FlowV2SessionStatus.COMPLETED
    effect = output.actions[0].as_effect()
    assert effect["media_type"] == "audio"
    assert effect["media_url"] == "https://cdn.example.com/audio.mp3"
    assert "caption" not in effect


def test_media_video_node_generates_action_with_optional_caption() -> None:
    executor, snapshot, _, _, db = _executor({"schema_version": 1, "start_node_id": "media", "nodes": [{"id": "media", "type": "media", "data": {"isStart": True, "media_type": "video", "media_url": "https://cdn.example.com/video.mp4", "caption": "Veja"}}], "edges": []})
    output = executor.handle_input(db, _input(snapshot))
    assert output.status == FlowV2SessionStatus.COMPLETED
    effect = output.actions[0].as_effect()
    assert effect["media_type"] == "video"
    assert effect["media_url"] == "https://cdn.example.com/video.mp4"
    assert effect["caption"] == "Veja"
