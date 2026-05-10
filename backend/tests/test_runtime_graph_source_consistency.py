from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.services import flow_engine_service as service


def _base_graph():
    return {
        "nodes": [
            {"id": str(uuid.uuid4()), "type": "message", "data": {"isStart": True}},
            {"id": str(uuid.uuid4()), "type": "condition", "data": {}},
        ],
        "edges": [],
    }


def test_start_and_continue_use_same_graph_source(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    version_id = uuid.uuid4()
    graph = _base_graph()
    flow = SimpleNamespace(id=flow_id, published_version_id=version_id)
    version = SimpleNamespace(id=version_id, nodes=graph["nodes"], edges=graph["edges"])

    monkeypatch.setattr(service, "resolve_flow", lambda **kwargs: flow)
    monkeypatch.setattr(service, "_get_flow_version_by_id", lambda **kwargs: version)

    start = service.load_published_runtime_graph(db=None, flow_id=str(flow_id), tenant_id=tenant_id)
    cont = service.load_published_runtime_graph(db=None, flow_id=str(flow_id), tenant_id=tenant_id, flow_version_id=version_id)

    assert start["source"] == "published_version"
    assert cont["source"] == "published_version"
    assert start["flow_version_id"] == cont["flow_version_id"]


def test_runtime_graph_empty_is_blocked(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    version_id = uuid.uuid4()
    flow = SimpleNamespace(id=flow_id, published_version_id=version_id)
    version = SimpleNamespace(id=version_id, nodes=[], edges=[])
    monkeypatch.setattr(service, "resolve_flow", lambda **kwargs: flow)
    monkeypatch.setattr(service, "_get_flow_version_by_id", lambda **kwargs: version)

    with pytest.raises(Exception):
        service.load_published_runtime_graph(db=None, flow_id=str(flow_id), tenant_id=tenant_id)


def test_runtime_graph_template_ids_are_blocked(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    version_id = uuid.uuid4()
    flow = SimpleNamespace(id=flow_id, published_version_id=version_id)
    version = SimpleNamespace(id=version_id, nodes=[{"id": "template-start", "type": "message", "data": {"isStart": True}}], edges=[])
    monkeypatch.setattr(service, "resolve_flow", lambda **kwargs: flow)
    monkeypatch.setattr(service, "_get_flow_version_by_id", lambda **kwargs: version)

    with pytest.raises(Exception):
        service.load_published_runtime_graph(db=None, flow_id=str(flow_id), tenant_id=tenant_id)
