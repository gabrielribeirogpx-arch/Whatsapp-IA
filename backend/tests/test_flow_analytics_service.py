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
