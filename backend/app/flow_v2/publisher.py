from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationResult
from app.flow_v2.snapshot import build_transitions_from_edges, canonical_hash

V2_SNAPSHOT_SCHEMA_VERSION = 1
FLOW_V2_ALLOWED_NODE_TYPES = frozenset({"message", "choice", "condition", "delay", "webhook", "transfer"})

logger = logging.getLogger(__name__)


class FlowV2PublishError(RuntimeError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("Flow V2 graph is invalid: " + "; ".join(errors))


class FlowV2SnapshotIntegrityError(RuntimeError):
    """Publication-time hard stop for invalid immutable Runtime V2 snapshots."""


@dataclass(frozen=True)
class FlowV2PublishResult:
    snapshot: dict[str, Any]
    v2_snapshot_hash: str
    validation: GraphValidationResult


def canonicalize_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a graph payload with stable object keys and stable node/edge order."""

    canonical_nodes = sorted(
        (_canonical_value(node) for node in nodes), key=_canonical_sort_key
    )
    canonical_edges = sorted(
        (_canonical_value(edge) for edge in edges), key=_canonical_sort_key
    )
    return {"nodes": canonical_nodes, "edges": canonical_edges}


def v2_snapshot_hash(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    nodes_payload = _runtime_v2_nodes_payload(copy.deepcopy(nodes))
    snapshot = _snapshot_payload(
        nodes=nodes_payload,
        edges=edges,
        start_node_id=_derive_start_node_id(nodes_payload),
    )
    return canonical_hash(snapshot)


def _runtime_v2_nodes_payload(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return nodes in the immutable Runtime V2 publication contract.

    The Flow Builder stores choice rows as ``data.buttons`` so it can keep its
    existing UI model.  Runtime V2 consumes ``options``.  During publication we
    keep the original builder fields for backward compatibility and add
    ``data.options`` when a choice node only has builder buttons.
    """

    return [_runtime_v2_node_payload(node) for node in nodes]


def _runtime_v2_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(node, dict):
        return node
    node_type = _strict_node_type(node)
    if node_type != "choice":
        return node

    data = _node_data(node)
    if _has_non_empty_options(node.get("options")) or _has_non_empty_options(
        data.get("options")
    ):
        return node

    options = _choice_options_from_buttons(data.get("buttons"))
    if not options:
        return node

    next_node = dict(node)
    next_data = dict(data)
    next_data["options"] = options
    next_node["data"] = next_data
    return next_node


def _strict_node_type(node: dict[str, Any]) -> str:
    raw_type = node.get("type")
    node_id = str(node.get("id") or "").strip()
    if raw_type is None or str(raw_type).strip() == "":
        raise FlowV2SnapshotIntegrityError(f"FLOW_V2_NODE_MISSING_TYPE:{node_id or '<missing-id>'}")
    node_type = str(raw_type).strip().lower()
    if node_type not in FLOW_V2_ALLOWED_NODE_TYPES:
        raise FlowV2SnapshotIntegrityError(f"FLOW_V2_UNKNOWN_NODE_TYPE:{node_id}:{node_type}")
    return node_type


def _validate_snapshot_nodes_or_raise(nodes: list[dict[str, Any]]) -> None:
    if not isinstance(nodes, list):
        raise FlowV2SnapshotIntegrityError("FLOW_V2_SNAPSHOT_NODES_MUST_BE_LIST")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise FlowV2SnapshotIntegrityError(f"FLOW_V2_NODE_{index}_INVALID")
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise FlowV2SnapshotIntegrityError(f"FLOW_V2_NODE_{index}_MISSING_ID")
        _strict_node_type(node)


def _log_snapshot_nodes(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        logger.info(
            "[V2 SNAPSHOT NODES] node_id=%s node_type=%s",
            node.get("id"),
            _strict_node_type(node),
        )


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _has_non_empty_options(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _choice_options_from_buttons(buttons: Any) -> list[dict[str, str]]:
    if not isinstance(buttons, list):
        return []

    options: list[dict[str, str]] = []
    for button in buttons:
        if not isinstance(button, dict):
            continue
        handle_id = str(button.get("handleId") or button.get("handle_id") or "").strip()
        label = str(button.get("label") or "").strip()
        if not handle_id or not label:
            continue
        options.append({"id": handle_id, "label": label})
    return options


class FlowV2Publisher:
    """Builds immutable Flow V2 publication snapshots from editor nodes and edges."""

    def __init__(self, *, validator: FlowV2GraphValidator | None = None) -> None:
        self.validator = validator or FlowV2GraphValidator()

    def publish(
        self, *, nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None
    ) -> FlowV2PublishResult:
        nodes_payload = _runtime_v2_nodes_payload(
            copy.deepcopy(nodes if isinstance(nodes, list) else [])
        )
        edges_payload = copy.deepcopy(edges if isinstance(edges, list) else [])
        _validate_snapshot_nodes_or_raise(nodes_payload)
        validation = self.validator.validate(nodes=nodes_payload, edges=edges_payload)
        if not validation.is_valid:
            raise FlowV2PublishError(validation.errors)

        start_node_id = self.validator._start_node_ids(nodes_payload)[0]
        snapshot = _snapshot_payload(
            nodes=nodes_payload, edges=edges_payload, start_node_id=start_node_id
        )
        _validate_snapshot_nodes_or_raise(snapshot["nodes"])
        _log_snapshot_nodes(snapshot["nodes"])
        snapshot_hash = canonical_hash(snapshot)
        snapshot = {**snapshot, "hash": snapshot_hash}
        return FlowV2PublishResult(
            snapshot=snapshot, v2_snapshot_hash=snapshot_hash, validation=validation
        )


def _snapshot_payload(
    *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], start_node_id: str
) -> dict[str, Any]:
    canonical_graph = canonicalize_graph(nodes, edges)
    transitions = build_transitions_from_edges(canonical_graph["edges"])
    logger.info(
        "[V2 SNAPSHOT] publishing start_node_id=%s nodes_count=%s edges_count=%s transitions_count=%s",
        start_node_id,
        len(canonical_graph["nodes"]),
        len(canonical_graph["edges"]),
        len(transitions),
    )
    logger.info(
        "[V2 TRANSITIONS] publishing transitions=%s edges=%s",
        transitions,
        canonical_graph["edges"],
    )
    return {
        "schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "version": "flow_v2_snapshot_v1",
        "start_node_id": start_node_id,
        "nodes": canonical_graph["nodes"],
        "edges": canonical_graph["edges"],
        "transitions": transitions,
    }


def _derive_start_node_id(nodes: list[dict[str, Any]]) -> str:
    start_node_ids = FlowV2GraphValidator._start_node_ids(nodes)
    return start_node_ids[0] if len(start_node_ids) == 1 else ""


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(value[key])
            for key in sorted(value.keys(), key=str)
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
