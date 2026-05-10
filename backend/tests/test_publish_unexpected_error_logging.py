from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')

from fastapi.responses import JSONResponse

from app.routers import flows


class DummyDB:
    def refresh(self, _obj):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


def _flow():
    return SimpleNamespace(id=uuid4(), published_version_id=uuid4(), version=1, status='draft', graph={"nodes": [], "edges": []})


def _version(nodes, edges):
    return SimpleNamespace(id=uuid4(), nodes=nodes, edges=edges)


def test_publish_unexpected_error_logs_trace_and_returns_debug_payload(monkeypatch):
    monkeypatch.setenv('DEBUG_PUBLISH_ERRORS', 'true')
    monkeypatch.setattr(flows, '_resolve_tenant_header', lambda _x: uuid4())
    monkeypatch.setattr(flows, '_get_flow_by_identifier', lambda **_kwargs: _flow())
    monkeypatch.setattr(
        flows,
        '_publish_fresh_snapshot',
        lambda **_kwargs: _version([{'id': 'n1', 'type': 'message', 'data': {'isStart': True}}], []),
    )
    monkeypatch.setattr(flows, '_builder_graph_from_flow', lambda _flow: ([{'id': 'n1', 'type': 'message', 'data': {'isStart': True}}], []))
    monkeypatch.setattr(flows, 'validate_flow_payload_or_400', lambda _nodes, _edges: None)
    monkeypatch.setattr(flows, 'validate_flow_graph', lambda _nodes, _edges, mode='publish': {'errors': [], 'warnings': []})
    monkeypatch.setattr(flows, 'invalidate_flow_runtime_cache', lambda _flow_id: None)

    def _explode(**_kwargs):
        raise RuntimeError('boom-debug')

    monkeypatch.setattr(flows, '_serialize_flow_version_response', _explode)

    calls: list[str] = []

    def _fake_exception(msg, *args, **kwargs):
        calls.append(msg % args if args else msg)

    monkeypatch.setattr(flows.logger, 'exception', _fake_exception)

    response = flows.publish_tenant_flow_version('flow-id', flows.PublishFlowPayload(), x_tenant_id='tenant-x', db=DummyDB())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert b'PUBLISH_FAILED' in response.body
    assert b'debug_type' in response.body
    assert b'RuntimeError' in response.body
    assert b'boom-debug' in response.body
    assert any('[PUBLISH FLOW UNEXPECTED ERROR]' in line for line in calls)
