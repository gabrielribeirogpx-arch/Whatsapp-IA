from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.flow_v2.delay_contract import normalize_delay_nodes
from app.flow_v2.publisher import FlowV2Publisher
from app.routers import flows
from app.services.flow_engine_service import validate_flow_graph


def _message_delay_message_nodes(delay_node: dict) -> list[dict]:
    return [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
        {"id": "delay", **delay_node},
        {"id": "after_delay", "type": "message", "data": {"text": "Depois", "isTerminal": True}},
    ]


def _message_delay_message_edges() -> list[dict]:
    return [
        {"id": "e1", "source": "start", "target": "delay"},
        {"id": "e2", "source": "delay", "target": "after_delay"},
    ]


def test_builder_save_preserves_runtime_v2_delay_seconds_before_validation() -> None:
    frontend_node = {
        "id": "delay",
        "type": "delay",
        "position": {"x": 100, "y": 100},
        "seconds": 5,
        "data": {"isStart": False},
    }

    rebuilt_node = flows._builder_node_for_save(frontend_node)
    normalized_node = normalize_delay_nodes([rebuilt_node])[0]

    assert rebuilt_node["seconds"] == 5
    assert normalized_node["seconds"] == 5
    assert "seconds" not in normalized_node.get("data", {})

    validation = validate_flow_graph(
        _message_delay_message_nodes({"type": "delay", "seconds": 5}),
        _message_delay_message_edges(),
        mode="draft",
    )

    assert validation["valid"] is True
    assert not any(error["code"] == "DELAY_INVALID" for error in validation["errors"])


def test_legacy_delay_content_is_normalized_to_runtime_v2_seconds() -> None:
    normalized_node = normalize_delay_nodes(
        [{"id": "delay", "type": "delay", "data": {"content": "5", "isStart": False}}]
    )[0]

    assert normalized_node["seconds"] == 5
    assert normalized_node.get("data") == {"isStart": False}

    validation = validate_flow_graph(
        _message_delay_message_nodes({"type": "delay", "data": {"content": "5"}}),
        _message_delay_message_edges(),
        mode="draft",
    )

    assert validation["valid"] is True
    assert not any(error["code"] == "DELAY_INVALID" for error in validation["errors"])


def test_delay_seconds_survives_save_reopen_save_round_trip() -> None:
    first_save_node = normalize_delay_nodes(
        [flows._builder_node_for_save({"id": "delay", "type": "delay", "seconds": 5, "data": {}})]
    )[0]
    reopened_and_saved_again = normalize_delay_nodes([flows._builder_node_for_save(first_save_node)])[0]

    assert first_save_node["seconds"] == 5
    assert reopened_and_saved_again["seconds"] == 5
    assert first_save_node["type"] == "delay"
    assert reopened_and_saved_again["type"] == "delay"


def test_message_delay_message_publishes_with_runtime_v2_delay_seconds() -> None:
    published = FlowV2Publisher().publish(
        nodes=[
            {"id": "start", "type": "message", "content": "Olá"},
            {"id": "delay", "type": "delay", "seconds": 5},
            {"id": "after_delay", "type": "message", "content": "Depois"},
        ],
        edges=[
            {"id": "e1", "source": "start", "target": "delay"},
            {"id": "e2", "source": "delay", "target": "after_delay"},
        ],
    )

    delay_node = next(node for node in published.snapshot["nodes"] if node["id"] == "delay")
    assert published.validation.is_valid
    assert delay_node["seconds"] == 5
    assert "seconds" not in delay_node.get("data", {})

def test_delay_show_typing_survives_save_normalize_and_publish() -> None:
    frontend_node = {
        "id": "delay",
        "type": "delay",
        "position": {"x": 100, "y": 100},
        "seconds": 5,
        "data": {"show_typing": True, "typing_duration_mode": "auto"},
    }

    rebuilt_node = flows._builder_node_for_save(frontend_node)
    normalized_node = normalize_delay_nodes([rebuilt_node])[0]
    published = FlowV2Publisher().publish(
        nodes=[
            {"id": "start", "type": "message", "content": "Olá"},
            normalized_node,
            {"id": "after_delay", "type": "message", "content": "Depois"},
        ],
        edges=[
            {"id": "e1", "source": "start", "target": "delay"},
            {"id": "e2", "source": "delay", "target": "after_delay"},
        ],
    )

    delay_node = next(node for node in published.snapshot["nodes"] if node["id"] == "delay")
    assert rebuilt_node["data"]["show_typing"] is True
    assert rebuilt_node["data"]["typing_duration_mode"] == "auto"
    assert normalized_node["data"]["show_typing"] is True
    assert normalized_node["data"]["typing_duration_mode"] == "auto"
    assert published.validation.is_valid
    assert delay_node["data"]["show_typing"] is True
    assert delay_node["data"]["typing_duration_mode"] == "auto"
