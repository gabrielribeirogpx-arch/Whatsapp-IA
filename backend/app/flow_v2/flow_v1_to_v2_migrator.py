from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.flow_v2.publisher import FlowV2Publisher
from app.flow_v2.node_registry import MIGRATABLE_NODE_TYPES


# Backward-compatible public name; the canonical list lives in node_registry.
SUPPORTED_V2_NODE_TYPES = MIGRATABLE_NODE_TYPES


@dataclass(frozen=True)
class FlowV1ToV2MigrationResult:
    snapshot: dict[str, Any]
    v2_snapshot_hash: str
    nodes_migrated: int
    edges_migrated: int
    warnings: tuple[str, ...] = ()


class FlowV1ToV2Migrator:
    """Converts persisted Flow V1 graph shapes into immutable Runtime V2 snapshots."""

    def __init__(self, *, publisher: FlowV2Publisher | None = None) -> None:
        self.publisher = publisher or FlowV2Publisher()

    def migrate(self, flow: Any) -> FlowV1ToV2MigrationResult:
        warnings: list[str] = []
        nodes = self._nodes_from_flow(flow, warnings)
        edges = self._edges_from_flow(flow, nodes, warnings)
        if nodes and not any(_is_start_node(node) for node in nodes):
            nodes[0] = {**nodes[0], "isStart": True}
            warnings.append(f"FLOW_V1_START_NODE_INFERRED:{nodes[0]['id']}")
        published = self.publisher.publish(nodes=nodes, edges=edges)
        return FlowV1ToV2MigrationResult(
            snapshot=published.snapshot,
            v2_snapshot_hash=published.v2_snapshot_hash,
            nodes_migrated=len(nodes),
            edges_migrated=len(edges),
            warnings=tuple(warnings),
        )

    def migrate_payload(self, *, nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None, steps: Iterable[Any] | None = None) -> FlowV1ToV2MigrationResult:
        flow = _PayloadFlow(nodes=nodes, edges=edges, steps=list(steps or []))
        return self.migrate(flow)

    def _nodes_from_flow(self, flow: Any, warnings: list[str]) -> list[dict[str, Any]]:
        raw_nodes = _first_list(getattr(flow, "nodes_json", None), getattr(flow, "nodes", None))
        if raw_nodes:
            return [self._normalize_node(node, index, warnings) for index, node in enumerate(raw_nodes)]

        node_records = list(getattr(flow, "node_records", None) or [])
        if node_records:
            return [self._normalize_node_record(record, index, warnings) for index, record in enumerate(node_records)]

        steps = list(getattr(flow, "steps", None) or [])
        return [self._normalize_step(step, index, warnings) for index, step in enumerate(steps)]

    def _edges_from_flow(self, flow: Any, nodes: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
        raw_edges = _first_list(getattr(flow, "edges_json", None), getattr(flow, "edges", None))
        if raw_edges:
            return [self._normalize_edge(edge, index) for index, edge in enumerate(raw_edges)]

        edge_records = list(getattr(flow, "edge_records", None) or [])
        if edge_records:
            return [self._normalize_edge_record(record, index) for index, record in enumerate(edge_records)]

        steps = list(getattr(flow, "steps", None) or [])
        if steps:
            return self._edges_from_steps(steps)

        if len(nodes) <= 1:
            return []
        warnings.append("FLOW_V1_EDGES_INFERRED_FROM_NODE_ORDER")
        return [{"id": f"edge_{index}", "source": str(nodes[index]["id"]), "target": str(nodes[index + 1]["id"])} for index in range(len(nodes) - 1)]

    def _normalize_node(self, node: Any, index: int, warnings: list[str]) -> dict[str, Any]:
        payload = dict(node) if isinstance(node, dict) else {"id": f"node_{index}", "type": "message", "content": str(node)}
        node_id = str(payload.get("id") or f"node_{index}")
        node_type = _node_type(payload)
        normalized = dict(payload)
        normalized["id"] = node_id
        if node_type in {"buttons", "buttons_node", "list", "list_node"}:
            normalized["type"] = "choice"
            data = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
            display_mode = "list" if node_type in {"list", "list_node"} else "buttons"
            normalized["data"] = {**data, "display_mode": display_mode}
            warnings.append(f"FLOW_V1_NODE_TYPE_MAPPED_TO_CHOICE:{node_id}:{node_type}:{display_mode}")
        elif node_type not in SUPPORTED_V2_NODE_TYPES:
            normalized["type"] = "message"
            data = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
            normalized["data"] = {**data, "v1_original_type": node_type}
            warnings.append(f"FLOW_V1_NODE_TYPE_MAPPED_TO_MESSAGE:{node_id}:{node_type}")
        else:
            normalized["type"] = node_type
        if normalized["type"] == "message" and not _message_content(normalized):
            normalized["content"] = str(payload.get("label") or payload.get("name") or "")
        return normalized

    def _normalize_node_record(self, record: Any, index: int, warnings: list[str]) -> dict[str, Any]:
        metadata = getattr(record, "metadata_json", None) or {}
        node = {
            "id": str(getattr(record, "id", f"node_{index}")),
            "type": getattr(record, "type", "message"),
            "content": getattr(record, "content", None),
            "data": dict(metadata) if isinstance(metadata, dict) else {},
        }
        if getattr(record, "position_x", None) is not None or getattr(record, "position_y", None) is not None:
            node["position"] = {"x": getattr(record, "position_x", 0) or 0, "y": getattr(record, "position_y", 0) or 0}
        return self._normalize_node(node, index, warnings)

    def _normalize_step(self, step: Any, index: int, warnings: list[str]) -> dict[str, Any]:
        node = {
            "id": str(getattr(step, "step_key", None) or f"step_{index}"),
            "type": "message",
            "content": getattr(step, "message", ""),
        }
        if index == 0:
            node["isStart"] = True
        return self._normalize_node(node, index, warnings)

    @staticmethod
    def _normalize_edge(edge: Any, index: int) -> dict[str, Any]:
        payload = dict(edge) if isinstance(edge, dict) else {}
        source = payload.get("source") or payload.get("from") or payload.get("source_node_id")
        target = payload.get("target") or payload.get("to") or payload.get("target_node_id")
        normalized = {**payload, "id": str(payload.get("id") or f"edge_{index}"), "source": str(source), "target": str(target)}
        handle = payload.get("sourceHandle") if payload.get("sourceHandle") is not None else payload.get("source_handle")
        if handle not in (None, ""):
            normalized["sourceHandle"] = str(handle)
        return normalized

    @staticmethod
    def _normalize_edge_record(record: Any, index: int) -> dict[str, Any]:
        edge = {
            "id": str(getattr(record, "id", f"edge_{index}")),
            "source": str(getattr(record, "source")),
            "target": str(getattr(record, "target")),
        }
        condition = getattr(record, "condition", None)
        if condition not in (None, ""):
            edge["sourceHandle"] = str(condition)
        return edge

    @staticmethod
    def _edges_from_steps(steps: list[Any]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for step in steps:
            source = str(getattr(step, "step_key", ""))
            next_step_map = getattr(step, "next_step_map", None) or {}
            if isinstance(next_step_map, dict) and next_step_map:
                for handle, target in sorted(next_step_map.items(), key=lambda item: str(item[0])):
                    edge = {"id": f"edge_{source}_{handle}", "source": source, "target": str(target)}
                    if handle not in (None, "", "default"):
                        edge["sourceHandle"] = str(handle)
                    edges.append(edge)
        return edges


def migrate_flow_v1_to_v2(flow: Any) -> FlowV1ToV2MigrationResult:
    return FlowV1ToV2Migrator().migrate(flow)


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return list(value)
    return []


def _node_type(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("type") or data.get("type") or "message").lower()


def _message_content(node: dict[str, Any]) -> Any:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return node.get("content") or node.get("text") or data.get("content") or data.get("text") or data.get("message")


def _is_start_node(node: dict[str, Any]) -> bool:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return bool(node.get("isStart") or node.get("is_start") or data.get("isStart") or data.get("is_start") or str(node.get("id")) == "start")


@dataclass
class _PayloadFlow:
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    steps: list[Any] | None = None
    nodes_json: list[dict[str, Any]] | None = None
    edges_json: list[dict[str, Any]] | None = None
