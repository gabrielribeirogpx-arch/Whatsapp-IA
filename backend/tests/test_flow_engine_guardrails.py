from app.services.flow_engine_service import validate_flow_structure


def _base_nodes():
    return [
        {"id": "start", "type": "message", "data": {"isStart": True}},
        {"id": "next", "type": "message", "data": {}},
    ]


def test_validate_flow_structure_accepts_valid_graph():
    nodes = _base_nodes()
    edges = [{"id": "e1", "source": "start", "target": "next"}]
    valid, error = validate_flow_structure(nodes, edges)
    assert valid is True
    assert error is None


def test_validate_flow_structure_rejects_duplicate_node_ids():
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True}},
        {"id": "start", "type": "message", "data": {}},
    ]
    valid, error = validate_flow_structure(nodes, [])
    assert valid is False
    assert "duplicado" in (error or "")


def test_validate_flow_structure_rejects_edges_to_unknown_nodes():
    nodes = _base_nodes()
    edges = [{"id": "e1", "source": "start", "target": "missing"}]
    valid, error = validate_flow_structure(nodes, edges)
    assert valid is False
    assert "inexistente" in (error or "")


def test_validate_flow_structure_accepts_condition_without_text():
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
        {"id": "cond", "type": "condition", "data": {"condition": "cliente vip", "text": None}},
    ]
    edges = [{"id": "e1", "source": "start", "target": "cond"}]

    valid, error = validate_flow_structure(nodes, edges)

    assert valid is True
    assert error is None


def test_validate_flow_structure_rejects_condition_without_condition():
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
        {"id": "cond", "type": "condition", "data": {"text": None}},
    ]
    edges = [{"id": "e1", "source": "start", "target": "cond"}]

    valid, error = validate_flow_structure(nodes, edges)

    assert valid is False
    assert "Condição sem conteúdo" in (error or "")
