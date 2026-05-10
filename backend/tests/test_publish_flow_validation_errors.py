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
    return SimpleNamespace(id=uuid4(), published_version_id=uuid4(), version=1, status='draft')


def _version(nodes, edges):
    return SimpleNamespace(id=uuid4(), nodes=nodes, edges=edges)


def test_graph_vazio_retorna_400(monkeypatch):
    monkeypatch.setattr(flows, '_resolve_tenant_header', lambda _x: uuid4())
    monkeypatch.setattr(flows, '_get_flow_by_identifier', lambda **_kwargs: _flow())
    monkeypatch.setattr(flows, '_publish_fresh_snapshot', lambda **_kwargs: _version([], []))

    response = flows.publish_tenant_flow_version('flow-id', flows.PublishFlowPayload(), x_tenant_id=None, db=DummyDB())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    assert b'INVALID_FLOW_GRAPH' in response.body


def test_template_ids_retorna_400(monkeypatch):
    monkeypatch.setattr(flows, '_resolve_tenant_header', lambda _x: uuid4())
    monkeypatch.setattr(flows, '_get_flow_by_identifier', lambda **_kwargs: _flow())
    monkeypatch.setattr(
        flows,
        '_publish_fresh_snapshot',
        lambda **_kwargs: _version([{'id': 'template-1', 'type': 'message', 'data': {'isStart': True}}], []),
    )

    response = flows.publish_tenant_flow_version('flow-id', flows.PublishFlowPayload(), x_tenant_id=None, db=DummyDB())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    assert b'INVALID_FLOW_GRAPH' in response.body


def test_edge_invalido_retorna_400(monkeypatch):
    monkeypatch.setattr(flows, '_resolve_tenant_header', lambda _x: uuid4())
    monkeypatch.setattr(flows, '_get_flow_by_identifier', lambda **_kwargs: _flow())
    monkeypatch.setattr(
        flows,
        '_publish_fresh_snapshot',
        lambda **_kwargs: _version(
            [
                {'id': 'n1', 'type': 'message', 'data': {'isStart': True}},
                {'id': 'n2', 'type': 'message', 'data': {}},
            ],
            [{'source': 'n1', 'target': 'n999'}],
        ),
    )

    response = flows.publish_tenant_flow_version('flow-id', flows.PublishFlowPayload(), x_tenant_id=None, db=DummyDB())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    assert b'INVALID_FLOW_GRAPH' in response.body


def test_graph_valido_publica(monkeypatch):
    flow = _flow()
    version = _version(
        [
            {'id': 'n1', 'type': 'message', 'data': {'isStart': True}},
            {'id': 'n2', 'type': 'message', 'data': {}},
        ],
        [{'source': 'n1', 'target': 'n2'}],
    )
    monkeypatch.setattr(flows, '_resolve_tenant_header', lambda _x: uuid4())
    monkeypatch.setattr(flows, '_get_flow_by_identifier', lambda **_kwargs: flow)
    monkeypatch.setattr(flows, '_publish_fresh_snapshot', lambda **_kwargs: version)
    monkeypatch.setattr(flows, '_builder_graph_from_flow', lambda _flow: (version.nodes, version.edges))
    monkeypatch.setattr(flows, 'validate_flow_payload_or_400', lambda _nodes, _edges: None)
    monkeypatch.setattr(flows, 'validate_flow_graph', lambda _nodes, _edges, mode='publish': {'errors': [], 'warnings': []})
    monkeypatch.setattr(flows, 'invalidate_flow_runtime_cache', lambda _flow_id: None)
    monkeypatch.setattr(flows, '_serialize_flow_version_response', lambda **_kwargs: {'ok': True})

    response = flows.publish_tenant_flow_version('flow-id', flows.PublishFlowPayload(), x_tenant_id=None, db=DummyDB())

    assert response == {'ok': True}
