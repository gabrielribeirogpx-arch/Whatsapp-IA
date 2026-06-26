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
    expanded_nodes, expanded_edges = _expand_ai_systems_for_runtime(copy.deepcopy(nodes), copy.deepcopy(edges))
    nodes_payload = _runtime_v2_nodes_payload(expanded_nodes)
    snapshot = _snapshot_payload(
        nodes=nodes_payload,
        edges=expanded_edges,
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

    expanded_nodes, _ = _expand_ai_systems_for_runtime(nodes, [])
    return [_runtime_v2_node_payload(node) for node in expanded_nodes]


AI_SYSTEM_INTERNAL_TYPES = {
    "ai_dispatcher",
    "ai_greeting",
    "ai_calendar_agent",
    "ai_safe_fallback",
}


def _expand_ai_systems_for_runtime(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile editor-only ai_system nodes into executable Runtime V2 nodes.

    The builder persists ai_system as one canvas node and stores its agents in
    data.internal_nodes/internal_edges. Runtime V2 snapshots must execute those
    internal agents, so publication expands them without changing the editor
    graph saved by the user.
    """

    logger.info("AI_SYSTEM_COMPILATION_STARTED")
    expanded_nodes: list[dict[str, Any]] = []
    expanded_edges: list[dict[str, Any]] = []
    ai_system_ids: set[str] = set()
    system_entry_by_id: dict[str, str] = {}
    system_exits_by_id: dict[str, list[str]] = {}

    for node in nodes:
        if not isinstance(node, dict):
            expanded_nodes.append(node)
            continue
        node_type = str(node.get("type") or _node_data(node).get("type") or "").strip()
        if node_type != "ai_system":
            expanded_nodes.append(node)
            continue

        system_id = str(node.get("id") or "").strip()
        if not system_id:
            continue
        ai_system_ids.add(system_id)
        data = _node_data(node)
        internal_nodes = data.get("internal_nodes") if isinstance(data.get("internal_nodes"), list) else []
        internal_edges = data.get("internal_edges") if isinstance(data.get("internal_edges"), list) else []
        id_map = {
            str(internal.get("id")): f"{system_id}__{internal.get('id')}"
            for internal in internal_nodes
            if isinstance(internal, dict) and internal.get("id") not in (None, "")
        }
        internal_start = next(
            (
                str(internal.get("id"))
                for internal in internal_nodes
                if isinstance(internal, dict) and bool(_node_data(internal).get("isStart"))
            ),
            next(iter(id_map), ""),
        )
        if internal_start and internal_start in id_map:
            system_entry_by_id[system_id] = id_map[internal_start]
            logger.info("AI_SYSTEM_INTERNAL_START_FOUND system_id=%s start_node_id=%s", system_id, id_map[internal_start])

        internal_sources = {str(edge.get("source")) for edge in internal_edges if isinstance(edge, dict) and edge.get("source") not in (None, "")}
        terminal_internal_ids = [internal_id for internal_id in id_map if internal_id not in internal_sources]
        system_exits_by_id[system_id] = [id_map[internal_id] for internal_id in terminal_internal_ids] or ([id_map[internal_start]] if internal_start in id_map else [])

        if bool(data.get("isStart")):
            start_id = f"{system_id}__start"
            expanded_nodes.append(
                {
                    "id": start_id,
                    "type": "start",
                    "position": node.get("position") or {"x": 0, "y": 0},
                    "data": {"isStart": True, "label": f"Start {data.get('label') or data.get('name') or 'AI System'}"},
                }
            )
            if internal_start and internal_start in id_map:
                expanded_edges.append(
                    {
                        "id": f"{start_id}->{id_map[internal_start]}",
                        "source": start_id,
                        "target": id_map[internal_start],
                        "sourceHandle": "default",
                        "targetHandle": "default",
                        "type": "default",
                        "label": "",
                        "data": {"sourceHandle": "default", "compiled_from_ai_system": system_id},
                    }
                )
        for internal in internal_nodes:
            if not isinstance(internal, dict) or str(internal.get("id")) not in id_map:
                continue
            internal_data = dict(_node_data(internal))
            internal_type = str(internal.get("type") or internal_data.get("type") or "ai_agent")
            internal_data.update(
                {
                    "compiled_from_ai_system": system_id,
                    "ai_system_internal_type": internal_type,
                    "isStart": False,
                    "allowed_tools": internal_data.get("allowed_tools") or ["responder"],
                    "max_steps": internal_data.get("max_steps") or 3,
                }
            )
            expanded_nodes.append(
                {
                    **internal,
                    "id": id_map[str(internal.get("id"))],
                    "type": "ai_agent" if internal_type in AI_SYSTEM_INTERNAL_TYPES else internal_type,
                    "data": internal_data,
                }
            )
        for edge in internal_edges:
            if not isinstance(edge, dict):
                continue
            source = id_map.get(str(edge.get("source")))
            target = id_map.get(str(edge.get("target")))
            if not source or not target:
                continue
            source_handle = (
                edge.get("sourceHandle")
                or edge.get("source_handle")
                or "default"
            )
            edge_id = edge.get("id") or f"{source}->{target}:{source_handle}"
            expanded_edges.append(
                {
                    **edge,
                    "id": f"{system_id}__{edge_id}",
                    "source": source,
                    "target": target,
                    "sourceHandle": source_handle,
                    "data": {**(edge.get("data") if isinstance(edge.get("data"), dict) else {}), "compiled_from_ai_system": system_id},
                }
            )
        logger.info("AI_SYSTEM_EXPANDED system_id=%s internal_nodes=%s internal_edges=%s", system_id, len(id_map), len(internal_edges))

    for edge in edges:
        if not isinstance(edge, dict):
            expanded_edges.append(edge)
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        source_handle = edge.get("sourceHandle") or edge.get("source_handle") or "default"
        if source in ai_system_ids and target in ai_system_ids:
            for source_exit in system_exits_by_id.get(source, []):
                target_entry = system_entry_by_id.get(target)
                if target_entry:
                    expanded_edges.append({**edge, "id": f"{edge.get('id') or source_exit + '->' + target_entry}__expanded", "source": source_exit, "target": target_entry, "sourceHandle": source_handle})
            continue
        if target in ai_system_ids:
            target_entry = system_entry_by_id.get(target)
            if target_entry:
                expanded_edges.append({**edge, "target": target_entry, "sourceHandle": source_handle})
            continue
        if source in ai_system_ids:
            for index, source_exit in enumerate(system_exits_by_id.get(source, [])):
                edge_id = str(edge.get("id") or f"{source_exit}->{target}:{source_handle}")
                expanded_edges.append({**edge, "id": edge_id if index == 0 else f"{edge_id}:{index}", "source": source_exit, "sourceHandle": source_handle})
            continue
        expanded_edges.append(edge)

    logger.info(
        "AI_SYSTEM_RUNTIME_GRAPH_CREATED nodes_count=%s edges_count=%s",
        len(expanded_nodes),
        len(expanded_edges),
    )
    logger.info("AI_SYSTEM_COMPILATION_FINISHED")
    return expanded_nodes, expanded_edges

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
        expanded_nodes, expanded_edges = _expand_ai_systems_for_runtime(
            copy.deepcopy(nodes if isinstance(nodes, list) else []),
            copy.deepcopy(edges if isinstance(edges, list) else []),
        )
        nodes_payload = _runtime_v2_nodes_payload(
            expanded_nodes
        )
        edges_payload = expanded_edges
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
