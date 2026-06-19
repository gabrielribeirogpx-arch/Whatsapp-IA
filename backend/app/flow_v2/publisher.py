from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.flow_v2.delay_contract import normalize_delay_nodes
from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationResult
from app.flow_v2.snapshot import build_transitions_from_edges, canonical_hash

V2_SNAPSHOT_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)


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
    node_type = str(
        node.get("type") or _node_data(node).get("type") or "message"
    ).lower()
    if node_type in {"buttons", "buttons_node", "list", "list_node"}:
        return _legacy_interactive_node_to_choice(node, node_type)
    if node_type == "ai_agent":
        return _sanitize_ai_agent_node(node)
    if node_type != "choice":
        return normalize_delay_nodes([node])[0]

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


def _sanitize_ai_agent_node(node: dict[str, Any]) -> dict[str, Any]:
    """Keep IA Agent MCP publication data to safe references only.

    MCP credentials live on tenant integration/server records and must never be
    copied into an immutable flow snapshot. The builder normally sends only
    ``mcp_tool_ids``; this also handles richer MCP payloads defensively.
    """
    next_node = normalize_delay_nodes([node])[0]
    data = _node_data(next_node)
    if not data:
        return next_node

    next_data = dict(data)
    if isinstance(next_data.get("mcp_tools"), list):
        next_data["mcp_tools"] = [
            _safe_mcp_tool_ref(item, next_data.get("max_mcp_calls"))
            for item in next_data["mcp_tools"]
            if isinstance(item, dict)
        ]
    if isinstance(next_data.get("mcpTools"), list):
        next_data["mcpTools"] = [
            _safe_mcp_tool_ref(
                item, next_data.get("maxMcpCalls", next_data.get("max_mcp_calls"))
            )
            for item in next_data["mcpTools"]
            if isinstance(item, dict)
        ]
    next_node = dict(next_node)
    next_node["data"] = next_data
    return next_node


def _safe_mcp_tool_ref(
    tool: dict[str, Any], default_max_calls: Any = None
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for source_key, target_key in (
        ("tool_id", "tool_id"),
        ("toolId", "tool_id"),
        ("id", "tool_id"),
        ("tool_name", "tool_name"),
        ("toolName", "tool_name"),
        ("name", "tool_name"),
        ("server_id", "server_id"),
        ("serverId", "server_id"),
        ("integration_id", "integration_id"),
        ("integrationId", "integration_id"),
    ):
        value = tool.get(source_key)
        if value not in (None, "") and target_key not in safe:
            safe[target_key] = str(value)
    if "enabled" in tool:
        safe["enabled"] = bool(tool.get("enabled"))
    elif "is_enabled" in tool:
        safe["enabled"] = bool(tool.get("is_enabled"))
    else:
        safe["enabled"] = True
    raw_max_calls = tool.get("max_calls", tool.get("maxCalls", default_max_calls))
    try:
        safe["max_calls"] = max(0, min(int(raw_max_calls), 3))
    except (TypeError, ValueError):
        safe["max_calls"] = 3
    return safe


def _legacy_interactive_node_to_choice(node: dict[str, Any], node_type: str) -> dict[str, Any]:
    data = _node_data(node)
    display_mode = "list" if node_type in {"list", "list_node"} else "buttons"
    next_node = dict(node)
    next_node["type"] = "choice"
    next_data = dict(data)
    next_data["display_mode"] = display_mode
    if display_mode == "buttons":
        options = _choice_options_from_buttons(next_data.get("buttons") or node.get("buttons"))
    else:
        options = _choice_options_from_sections(next_data.get("sections") or node.get("sections"))
    if options and not (_has_non_empty_options(node.get("options")) or _has_non_empty_options(next_data.get("options"))):
        next_data["options"] = options
    if "content" not in next_data and next_data.get("body_text"):
        next_data["content"] = next_data.get("body_text")
    next_node["data"] = next_data
    return next_node


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _has_non_empty_options(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _choice_options_from_sections(sections: Any) -> list[dict[str, str]]:
    if not isinstance(sections, list):
        return []

    options: list[dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        rows = section.get("rows") if isinstance(section.get("rows"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            handle_id = str(row.get("handleId") or row.get("handle_id") or row.get("id") or "").strip()
            label = str(row.get("label") or row.get("title") or "").strip()
            if not handle_id or not label:
                continue
            option: dict[str, str] = {"id": handle_id, "label": label}
            description = str(row.get("description") or "").strip()
            if description:
                option["description"] = description
            options.append(option)
    return options


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
