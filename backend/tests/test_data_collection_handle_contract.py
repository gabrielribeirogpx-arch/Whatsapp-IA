from app.flow_v2.data_collection_handles import HANDLES, normalize_data_collection_edges
from app.services.flow_validation import validate_builder_graph


def _nodes(**overrides):
    data = {
        "isStart": True, "variable_name": "email", "data_type": "email",
        "max_attempts": 3, "timeout_seconds": 0, "cancel_keywords": [],
        "auto_retry_invalid": True, "attempts_exceeded_behavior": "end",
        **overrides,
    }
    return [
        {"id": "collect", "type": "data_collection", "data": data},
        {"id": "end", "type": "message", "data": {"content": "Fim", "isEnd": True}},
    ]


def _edges(*handles):
    return [
        {"id": f"e-{handle}", "source": "collect", "target": "end", "sourceHandle": handle, "targetHandle": "default"}
        for handle in handles
    ]


def _connection_messages(nodes, edges):
    return [issue["message"] for issue in validate_builder_graph(nodes, edges) if issue["field"] == "connections"]


def test_only_success_connected_when_optional_outputs_are_disabled():
    assert _connection_messages(_nodes(), _edges("success")) == []


def test_success_and_cancel_connected():
    nodes = _nodes(cancel_keywords=["cancelar"])
    assert _connection_messages(nodes, _edges("success", "cancel")) == []


def test_success_and_timeout_connected():
    nodes = _nodes(timeout_seconds=30)
    assert _connection_messages(nodes, _edges("success", "timeout")) == []


def test_all_rendered_outputs_use_the_canonical_contract():
    nodes = _nodes(timeout_seconds=30, cancel_keywords=["cancelar"], attempts_exceeded_behavior="invalid")
    assert HANDLES == ("success", "cancel", "timeout", "invalid")
    assert _connection_messages(nodes, _edges(*HANDLES)) == []


def test_automatic_retry_allows_default_fallback_when_exhausted_route_is_missing():
    continuing = _nodes(auto_retry_invalid=True, attempts_exceeded_behavior="invalid")
    assert _connection_messages(continuing, _edges("success")) == []
    assert _connection_messages(continuing, _edges("success", "invalid")) == []


def test_manual_retry_routes_invalid_input():
    nodes = _nodes(auto_retry_invalid=False)
    assert _connection_messages(nodes, _edges("success")) == []
    assert _connection_messages(nodes, _edges("success", "invalid")) == []


def test_saved_reloaded_and_published_shape_preserves_all_edge_fields():
    nodes = _nodes()
    saved = _edges("success")
    reloaded = normalize_data_collection_edges(nodes, saved)
    published = normalize_data_collection_edges(nodes, reloaded)
    assert published == reloaded
    assert published[0]["sourceHandle"] == saved[0]["sourceHandle"]
    assert {"source", "target", "sourceHandle", "targetHandle"}.issubset(published[0])


def test_legacy_retry_exhausted_is_migrated_without_reconnecting_missing_handles():
    nodes = _nodes(attempts_exceeded_behavior="invalid")
    legacy = _edges("success", "retry_exhausted")
    migrated = normalize_data_collection_edges(nodes, legacy)
    assert [edge["sourceHandle"] for edge in migrated] == ["success", "invalid"]
    assert _connection_messages(nodes, migrated) == []
    missing = [{"source": "collect", "target": "end"}]
    assert "sourceHandle" not in normalize_data_collection_edges(nodes, missing)[0]
