from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid

from app.services.flow_analytics_service import (
    FLOW_COMPLETED,
    FLOW_STARTED,
    MESSAGE_RECEIVED,
    NODE_ENTERED,
    NODE_EXITED,
    get_flow_analytics,
    get_flow_list_metrics,
)


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_, **__):
        return self

    def order_by(self, *_, **__):
        return self

    def group_by(self, *_, **__):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _DB:
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __init__(self, *, flow, executions, events, nodes, sessions=None):
        self.flow = flow
        self.executions = executions
        self.events = events
        self.nodes = nodes
        self.sessions = sessions or []

    def query(self, *entities):
        names = [getattr(entity, "__name__", str(entity)) for entity in entities]
        text = " ".join(names)
        if "FlowExecutionEvent" in text:
            return _Query(self.events)
        if "FlowSession" in text:
            return _Query(self.sessions)
        if "FlowExecution" in text:
            return _Query(self.executions)
        if "FlowNode" in text:
            return _Query(self.nodes)
        if "Flow" in text:
            return _Query([self.flow])
        return _Query([])


def test_flow_analytics_uses_persisted_execution_events():
    flow_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    started_at = datetime.utcnow() - timedelta(minutes=5)
    completed_at = started_at + timedelta(minutes=2)
    node_id = uuid.uuid4()
    db = _DB(
        flow=SimpleNamespace(id=flow_id, tenant_id=tenant_id, name="Flow real"),
        executions=[SimpleNamespace(id=execution_id, started_at=started_at, completed_at=completed_at, completed=True, status="completed")],
        events=[
            SimpleNamespace(execution_id=execution_id, node_id=str(node_id), event_type=FLOW_STARTED, created_at=started_at, metadata_json={}),
            SimpleNamespace(execution_id=execution_id, node_id=str(node_id), event_type=NODE_ENTERED, created_at=started_at, metadata_json={}),
            SimpleNamespace(execution_id=execution_id, node_id=str(node_id), event_type=MESSAGE_RECEIVED, created_at=started_at, metadata_json={"text": "sim"}),
            SimpleNamespace(execution_id=execution_id, node_id=str(node_id), event_type=NODE_EXITED, created_at=completed_at, metadata_json={}),
            SimpleNamespace(execution_id=execution_id, node_id=str(node_id), event_type=FLOW_COMPLETED, created_at=completed_at, metadata_json={}),
        ],
        nodes=[SimpleNamespace(id=node_id, type="message", content="Boas-vindas", metadata_json={"label": "Início"})],
    )

    analytics = get_flow_analytics(db=db, tenant_id=tenant_id, flow_id=flow_id, period="7d")

    assert analytics["summary"]["entries"] == 1
    assert analytics["summary"]["completed"] == 1
    assert analytics["summary"]["conversion_rate"] == 100
    assert analytics["summary"]["messages_sent"] == 1
    assert analytics["funnel"][0]["node_label"] == "Início"
    assert analytics["funnel"][0]["entries"] == 1
    assert analytics["common_replies"][0]["reply"] == "sim"


def test_flow_list_metrics_are_derived_from_executions():
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    now = datetime.utcnow()
    db = _DB(
        flow=SimpleNamespace(id=flow_id, tenant_id=tenant_id, name="Flow real"),
        executions=[(flow_id, 2, 1, now)],
        events=[],
        nodes=[],
    )

    metrics = get_flow_list_metrics(db=db, tenant_id=tenant_id)

    assert metrics[flow_id]["total_entries"] == 2
    assert metrics[flow_id]["total_completions"] == 1
    assert metrics[flow_id]["conversion_rate"] == 50


def test_record_flow_event_keeps_versioned_runtime_node_out_of_flow_events_fk():
    from app.models.flow_event import FlowEvent
    from app.services.flow_analytics_service import record_flow_event

    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    versioned_node_id = uuid.uuid4()

    class _RecordingDB(_DB):
        def __init__(self):
            super().__init__(flow=SimpleNamespace(id=flow_id, tenant_id=tenant_id, name="Flow"), executions=[], events=[], nodes=[], sessions=[])
            self.added = []
            self.flushes = 0

        def add(self, item):
            self.added.append(item)

        def flush(self):
            self.flushes += 1

    db = _RecordingDB()

    record_flow_event(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        node_id=versioned_node_id,
        event_type=NODE_ENTERED,
        metadata={"source": "published_version"},
    )

    flow_event = next(item for item in db.added if isinstance(item, FlowEvent))
    assert flow_event.node_id is None
    assert flow_event.metadata_json["runtime_node_id"] == str(versioned_node_id)
    assert flow_event.metadata_json["node_id_unpersisted"] is True

    execution_event = db.added[-1]
    assert execution_event.node_id == str(versioned_node_id)
