from __future__ import annotations

import os
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.flow_v2.publisher import FlowV2Publisher
from app.flow_v2.snapshot import FlowV2SnapshotError, FlowV2SnapshotRepository
from app.routers import flows

NODES = [
    {"id": "n1", "type": "message", "data": {"isStart": True, "text": "Olá"}},
    {"id": "n2", "type": "message", "data": {"text": "Fim"}},
]
EDGES = [{"id": "e1", "source": "n1", "target": "n2"}]


class _Scalar:
    def __init__(self, value=None):
        self.value = value

    def scalar(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class _Query:
    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return None

    def update(self, *_args, **_kwargs):
        return 1


class _PublishDB:
    def __init__(self):
        self.added = []

    def begin_nested(self):
        return nullcontext()

    def execute(self, *_args, **_kwargs):
        return _Scalar(0)

    def query(self, *_args, **_kwargs):
        return _Query()

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None


def test_publish_fresh_snapshot_generates_v2_snapshot_hash(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        runtime="v2",
        nodes_json=NODES,
        edges_json=EDGES,
        nodes=None,
        edges=None,
        current_version=None,
        current_version_id=None,
        published_version_id=None,
        published_version=None,
        version=1,
    )
    monkeypatch.setattr(
        flows, "_builder_graph_from_records", lambda _db, _flow: (NODES, EDGES)
    )
    monkeypatch.setattr(
        flows, "validate_flow_payload_or_400", lambda _nodes, _edges: None
    )

    version = flows._publish_fresh_snapshot(
        db=_PublishDB(), flow=flow, reason="publish"
    )

    assert version is not None
    assert version.v2_snapshot_hash
    assert version.graph_checksum == version.v2_snapshot_hash
    assert version.snapshot["hash"] == version.v2_snapshot_hash
    assert version.snapshot["transitions"] == [
        {"id": "e1", "source_node_id": "n1", "target_node_id": "n2", "edge_id": "e1"}
    ]
    assert (
        version.v2_snapshot_schema_version
        == version.snapshot["snapshot_schema_version"]
        == 1
    )
    assert version.start_node_id == "n1"
    assert flow.published_version_id == version.id


def test_publish_fresh_snapshot_keeps_v1_without_v2_hash(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        runtime="v1",
        nodes_json=NODES,
        edges_json=EDGES,
        nodes=None,
        edges=None,
        current_version=None,
        current_version_id=None,
        published_version_id=None,
        published_version=None,
        version=1,
    )
    monkeypatch.setattr(
        flows, "_builder_graph_from_records", lambda _db, _flow: (NODES, EDGES)
    )
    monkeypatch.setattr(
        flows, "validate_flow_payload_or_400", lambda _nodes, _edges: None
    )

    version = flows._publish_fresh_snapshot(
        db=_PublishDB(), flow=flow, reason="publish"
    )

    assert version is not None
    assert version.v2_snapshot_hash is None
    assert version.snapshot == {"nodes": NODES, "edges": EDGES}


def test_snapshot_repository_loads_immutable_unpublished_replaced_version():
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    published = FlowV2Publisher().publish(nodes=NODES, edges=EDGES)
    version = SimpleNamespace(
        id=flow_version_id,
        tenant_id=tenant_id,
        is_published=False,
        snapshot=published.snapshot,
        v2_snapshot_hash=published.v2_snapshot_hash,
        v2_snapshot_schema_version=published.snapshot["snapshot_schema_version"],
    )

    class _DB:
        def execute(self, *_args, **_kwargs):
            return _Scalar(version)

    snapshot = FlowV2SnapshotRepository().load(
        _DB(), tenant_id=tenant_id, flow_version_id=flow_version_id
    )

    assert snapshot.flow_version_id == flow_version_id
    assert snapshot.tenant_id == tenant_id
    assert snapshot.hash == published.v2_snapshot_hash
    assert snapshot.start_node_id == "n1"


def test_snapshot_repository_rejects_schema_version_mismatch():
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    published = FlowV2Publisher().publish(nodes=NODES, edges=EDGES)
    version = SimpleNamespace(
        id=flow_version_id,
        tenant_id=tenant_id,
        is_published=True,
        snapshot=published.snapshot,
        v2_snapshot_hash=published.v2_snapshot_hash,
        v2_snapshot_schema_version=2,
    )

    class _DB:
        def execute(self, *_args, **_kwargs):
            return _Scalar(version)

    with pytest.raises(FlowV2SnapshotError, match="schema version mismatch"):
        FlowV2SnapshotRepository().load(
            _DB(), tenant_id=tenant_id, flow_version_id=flow_version_id
        )


def test_publish_fresh_snapshot_converts_builder_choice_buttons_for_runtime_v2(
    monkeypatch,
):
    tenant_id = uuid.uuid4()
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
        {
            "id": "choice",
            "type": "choice",
            "data": {
                "content": "Escolha",
                "buttons": [
                    {
                        "id": "choice-1",
                        "label": "Quero planos",
                        "handleId": "quero_planos",
                    },
                    {"id": "choice-2", "label": "Humano", "handleId": "humano"},
                ],
            },
        },
        {"id": "end", "type": "message", "data": {"text": "Fim"}},
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "choice"},
        {
            "id": "e2",
            "source": "choice",
            "sourceHandle": "quero_planos",
            "target": "end",
        },
        {"id": "e3", "source": "choice", "sourceHandle": "humano", "target": "end"},
    ]
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        runtime="v2",
        nodes_json=nodes,
        edges_json=edges,
        nodes=None,
        edges=None,
        current_version=None,
        current_version_id=None,
        published_version_id=None,
        published_version=None,
        version=1,
    )
    monkeypatch.setattr(
        flows, "_builder_graph_from_records", lambda _db, _flow: (nodes, edges)
    )
    monkeypatch.setattr(
        flows, "validate_flow_payload_or_400", lambda _nodes, _edges: None
    )

    version = flows._publish_fresh_snapshot(
        db=_PublishDB(), flow=flow, reason="publish"
    )

    assert version is not None
    choice = next(node for node in version.snapshot["nodes"] if node["id"] == "choice")
    assert choice["data"]["options"] == [
        {"id": "quero_planos", "label": "Quero planos"},
        {"id": "humano", "label": "Humano"},
    ]
    assert choice["data"]["buttons"] == nodes[1]["data"]["buttons"]
    assert "options" not in nodes[1]["data"]


def test_publish_graph_selection_prefers_react_flow_json_edges_when_records_are_partial():
    record_nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
        {"id": "delay", "type": "delay", "data": {"seconds": 5}},
    ]
    flow_nodes = [dict(node) for node in record_nodes]
    flow_edges = [{"id": "e1", "source": "start", "target": "delay"}]

    nodes, edges, source = flows._select_publish_builder_graph(
        flow_nodes=flow_nodes,
        flow_edges=flow_edges,
        record_nodes=record_nodes,
        record_edges=[],
    )

    assert source == "flow_json"
    assert nodes == flow_nodes
    assert edges == flow_edges


def test_snapshot_audit_report_identifies_requested_missing_transition():
    from app.flow_v2.snapshot import FlowV2Snapshot, build_snapshot_transition_audit

    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    snapshot = FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash="hash",
        nodes=tuple(NODES),
        edges=tuple(EDGES),
        transitions=(),
        start_node_id="n1",
    )

    report = build_snapshot_transition_audit(snapshot, source_node_id="missing")

    assert report["start_node_id"] == "n1"
    assert report["transitions_found"] == [
        {"id": "e1", "source_node_id": "n1", "target_node_id": "n2", "edge_id": "e1"}
    ]
    assert report["requested_transition"]["missing"] is True
    assert report["requested_transition"]["outgoing_transitions"] == []


def test_activate_uses_published_runtime_snapshot_not_editor_graph(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.routers import flows

    tenant_id = uuid4()
    flow_id = uuid4()
    version_id = uuid4()
    runtime_nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Oi"}},
        {"id": "end", "type": "message", "data": {"text": "Fim", "isTerminal": True}},
    ]
    runtime_edges = [{"id": "edge-runtime", "source": "start", "target": "end"}]
    editor_nodes = [{"id": "ai_system", "type": "ai_system", "data": {"isStart": True}}]
    editor_edges = [{"id": "edge-editor-stale", "source": "ai_system", "target": "missing"}]
    flow = SimpleNamespace(
        id=flow_id,
        tenant_id=tenant_id,
        published_version_id=version_id,
        current_version_id=None,
        version=1,
        status="published",
        nodes_json=editor_nodes,
        edges_json=editor_edges,
        nodes=editor_nodes,
        edges=editor_edges,
        current_version=None,
    )
    version = SimpleNamespace(
        id=version_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        version=7,
        is_published=True,
        snapshot={"nodes": runtime_nodes, "edges": runtime_edges, "snapshot_schema_version": 2},
        nodes=runtime_nodes,
        edges=runtime_edges,
    )

    class _ScalarResult:
        def first(self):
            return version

    class _ExecuteResult:
        def scalars(self):
            return _ScalarResult()

    class _DB:
        def __init__(self):
            self.added = []

        def execute(self, *_args, **_kwargs):
            return _ExecuteResult()

        def add(self, obj):
            self.added.append(obj)

    def fail_publish(**_kwargs):
        raise AssertionError("activate must not republish when a published snapshot exists")

    validated = []
    monkeypatch.setattr(flows, "_publish_fresh_snapshot", fail_publish)
    monkeypatch.setattr(flows, "invalidate_flow_runtime_cache", lambda _flow_id: None)
    monkeypatch.setattr(flows, "validate_flow_graph", lambda nodes, edges, mode="publish": validated.append((nodes, edges, mode)) or {"errors": [], "warnings": []})

    flows._ensure_published_snapshot_on_activate(db=_DB(), flow=flow)

    assert validated == [(runtime_nodes, runtime_edges, "publish")]
    assert flow.published_version_id == version_id
    assert flow.current_version_id == version_id
    assert flow.version == 7
