from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.routers.flows import _validate_no_template_ids


def test_published_graph_rejects_template_ids_in_nodes_and_edges():
    nodes = [{"id": "template-condition-123", "type": "condition", "data": {}}]
    edges = [{"source": "template-condition-123", "target": "template-message-456"}]

    with pytest.raises(RuntimeError, match="FLOW CONTAINS TEMP NODE IDS"):
        _validate_no_template_ids(nodes, edges)


def test_published_graph_accepts_persisted_ids_and_session_node_exists_in_runtime_graph():
    nodes = [
        {"id": "15a600a5-5bf3-4d2e-96f3-c7059f60f7dd", "type": "message", "data": {"isStart": True}},
        {"id": "127bcf3a-0064-4fce-86b0-5721ba6188e2", "type": "condition", "data": {}},
    ]
    edges = [
        {
            "source": "15a600a5-5bf3-4d2e-96f3-c7059f60f7dd",
            "target": "127bcf3a-0064-4fce-86b0-5721ba6188e2",
        }
    ]

    _validate_no_template_ids(nodes, edges)

    runtime_node_ids = {str(node["id"]) for node in nodes}
    session_current_node_id = "127bcf3a-0064-4fce-86b0-5721ba6188e2"
    assert session_current_node_id in runtime_node_ids
