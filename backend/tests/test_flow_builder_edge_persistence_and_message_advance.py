from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.routers.flows import _normalize_flow_edges, _persist_builder_graph
from app.schemas.flow import EdgeSchema
from app.services import flow_engine_service as service


def test_edge_schema_and_normalizer_preserve_reactflow_handles_and_data():
    edge = EdgeSchema(
        id="edge-1",
        source="message-a",
        target="message-b",
        sourceHandle="default",
        targetHandle="target-default",
        type="default",
        label="next",
        data={"sourceHandle": "default", "condition": "next", "custom": "kept"},
    )

    normalized = _normalize_flow_edges([edge])

    assert normalized == [
        {
            "id": "edge-1",
            "source": "message-a",
            "target": "message-b",
            "sourceHandle": "default",
            "targetHandle": "target-default",
            "type": "default",
            "label": "next",
            "data": {"sourceHandle": "default", "condition": "next", "custom": "kept"},
        }
    ]


def test_builder_graph_persists_flow_json_columns_integrally():
    flow = SimpleNamespace(nodes_json=None, edges_json=None, nodes=None, edges=None)
    nodes = [{"id": "message-a", "type": "message", "data": {"text": "A"}}]
    edges = [{"id": "edge-1", "source": "message-a", "target": "message-b", "sourceHandle": "default"}]

    _persist_builder_graph(flow, nodes, edges)

    assert flow.nodes_json == nodes
    assert flow.edges_json == edges
    assert flow.nodes == nodes
    assert flow.edges == edges


def test_runtime_resolves_message_to_message_edge_even_when_source_key_is_text():
    flow_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    node_a = service.VersionedFlowNode(
        id=uuid.uuid4(),
        flow_id=flow_id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito! Vou te direcionar para o suporte.",
        metadata_json={"text": "Perfeito! Vou te direcionar para o suporte."},
        position_x=0,
        position_y=0,
    )
    node_b = service.VersionedFlowNode(
        id=uuid.uuid4(),
        flow_id=flow_id,
        tenant_id=tenant_id,
        type="message",
        content="Aguarde mais um momento",
        metadata_json={"text": "Aguarde mais um momento"},
        position_x=100,
        position_y=0,
    )
    edge = service.VersionedFlowEdge(
        id=uuid.uuid4(),
        flow_id=flow_id,
        source=node_a.id,
        target=node_b.id,
        condition="default",
        source_handle="default",
    )
    runtime_graph = {
        "nodes": [node_a, node_b],
        "edges": [edge],
        "node_map": service.build_node_map([node_a, node_b]),
        "edges_by_source": {str(node_a.id): [edge]},
    }

    outgoing = service._get_edges(db=None, flow_id=flow_id, source=node_a.id, runtime_graph=runtime_graph)
    next_edge = service._pick_default_edge(outgoing)
    next_node = service._get_node(db=None, node_id=service._edge_target(next_edge), tenant_id=tenant_id, runtime_graph=runtime_graph)

    assert outgoing == [edge]
    assert next_node == node_b
