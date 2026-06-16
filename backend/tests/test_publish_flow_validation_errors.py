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


def test_publish_fresh_snapshot_republishes_latest_matching_checksum(monkeypatch):
    tenant_id = uuid4()
    flow_id = uuid4()
    old_published_id = uuid4()
    latest_id = uuid4()
    nodes = [
        {'id': 'n1', 'type': 'message', 'data': {'isStart': True, 'text': 'Inicio'}},
        {'id': 'n2', 'type': 'message', 'data': {'text': 'Aguarde'}},
        {'id': 'n3', 'type': 'message', 'data': {'text': 'Aguarde mais um momento'}},
        {'id': 'n4', 'type': 'message', 'data': {'text': 'Quase lá'}},
        {'id': 'n5', 'type': 'message', 'data': {'text': 'Fim'}},
    ]
    edges = [
        {'source': 'n1', 'target': 'n2'},
        {'source': 'n2', 'target': 'n3'},
        {'source': 'n3', 'target': 'n4'},
        {'source': 'n4', 'target': 'n5'},
    ]
    latest_version = SimpleNamespace(
        id=latest_id,
        version=7,
        nodes=nodes,
        edges=edges,
        snapshot={'nodes': nodes, 'edges': edges},
        graph_checksum=flows._graph_checksum(nodes, edges),
        start_node_id=None,
        start_text_preview=None,
        created_from_source=None,
        is_active=False,
        is_published=False,
    )
    flow = SimpleNamespace(
        id=flow_id,
        tenant_id=tenant_id,
        nodes_json=nodes,
        edges_json=edges,
        nodes=None,
        edges=None,
        current_version=None,
        current_version_id=uuid4(),
        published_version_id=old_published_id,
        published_version=SimpleNamespace(id=old_published_id, nodes=nodes[:4], edges=edges[:3]),
        version=6,
    )

    class ScalarResult:
        def scalar(self):
            return latest_version.version

    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def first(self):
            return latest_version

        def update(self, values, synchronize_session=False):
            latest_version.is_active = values.get(flows.FlowVersion.is_active, values.get('is_active', latest_version.is_active))
            latest_version.is_published = values.get(flows.FlowVersion.is_published, values.get('is_published', latest_version.is_published))
            return 1

    class DB:
        def query(self, *_args, **_kwargs):
            return Query()

        def execute(self, *_args, **_kwargs):
            return ScalarResult()

        def add(self, _obj):
            return None

        def flush(self):
            return None

    monkeypatch.setattr(flows, 'validate_flow_payload_or_400', lambda _nodes, _edges: None)
    published = flows._publish_fresh_snapshot(db=DB(), flow=flow, reason='publish')

    assert published is latest_version
    assert latest_version.is_active is True
    assert latest_version.is_published is True
    assert flow.published_version_id == latest_id
    assert flow.current_version_id == latest_id
    assert len(published.nodes) == 5
    assert published.nodes[2]['data']['text'] == 'Aguarde mais um momento'


def test_validate_flow_graph_accepts_ai_rag_wait_same_node_without_edge():
    result = flows.validate_flow_graph(
        [{'id': 'rag', 'type': 'ai_rag', 'data': {'isStart': True, 'after_answer_behavior': 'wait_same_node'}}],
        [],
        mode='publish',
    )

    assert result['errors'] == []
    assert result['warnings'] == []


def test_validate_flow_graph_accepts_ai_rag_end_flow_without_edge():
    result = flows.validate_flow_graph(
        [{'id': 'rag', 'type': 'ai_rag', 'data': {'isStart': True, 'after_answer_behavior': 'end_flow'}}],
        [],
        mode='publish',
    )

    assert result['errors'] == []
    assert result['warnings'] == []


def test_validate_flow_graph_requires_ai_rag_continue_to_next_edge():
    result = flows.validate_flow_graph(
        [{'id': 'rag', 'type': 'ai_rag', 'data': {'isStart': True, 'after_answer_behavior': 'continue_to_next'}}],
        [],
        mode='publish',
    )

    assert any(issue['code'] == 'NODE_WITHOUT_OUTPUT' and issue['node_id'] == 'rag' for issue in result['errors'])
