from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationResult
from app.flow_v2.snapshot import canonical_hash

V2_SNAPSHOT_SCHEMA_VERSION = 1


class FlowV2PublishError(RuntimeError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("Flow V2 graph is invalid: " + "; ".join(errors))


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
    snapshot = _snapshot_payload(
        nodes=nodes, edges=edges, start_node_id=_derive_start_node_id(nodes)
    )
    return canonical_hash(snapshot)


class FlowV2Publisher:
    """Builds immutable Flow V2 publication snapshots from editor nodes and edges."""

    def __init__(self, *, validator: FlowV2GraphValidator | None = None) -> None:
        self.validator = validator or FlowV2GraphValidator()

    def publish(
        self, *, nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None
    ) -> FlowV2PublishResult:
        nodes_payload = copy.deepcopy(nodes if isinstance(nodes, list) else [])
        edges_payload = copy.deepcopy(edges if isinstance(edges, list) else [])
        validation = self.validator.validate(nodes=nodes_payload, edges=edges_payload)
        if not validation.is_valid:
            raise FlowV2PublishError(validation.errors)

        start_node_id = self.validator._start_node_ids(nodes_payload)[0]
        snapshot = _snapshot_payload(
            nodes=nodes_payload, edges=edges_payload, start_node_id=start_node_id
        )
        snapshot_hash = canonical_hash(snapshot)
        snapshot = {**snapshot, "hash": snapshot_hash}
        return FlowV2PublishResult(
            snapshot=snapshot, v2_snapshot_hash=snapshot_hash, validation=validation
        )


def _snapshot_payload(
    *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], start_node_id: str
) -> dict[str, Any]:
    canonical_graph = canonicalize_graph(nodes, edges)
    return {
        "schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "version": "flow_v2_snapshot_v1",
        "start_node_id": start_node_id,
        "nodes": canonical_graph["nodes"],
        "edges": canonical_graph["edges"],
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
