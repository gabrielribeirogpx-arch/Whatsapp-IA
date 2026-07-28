from __future__ import annotations
from collections import deque
from typing import Any
from .catalog import NODE_TYPES

AI_TYPES = {"ai_rag", "ai_response", "ai_classification", "ai_extraction", "ai_summary", "ai_agent", "ai_supervisor", "ai_system"}
SINGLE_OUTPUT_TYPES = {"message", "action", "ai_classification"}

def _edge_handle(edge: dict[str, Any], side: str) -> str:
    return str(edge.get(f"{side}Handle", edge.get(f"{side}_handle")) or "").strip()

def _condition_handles(node: dict[str, Any]) -> list[str]:
    """Mirror the handles rendered by ConditionNode, including its true/false defaults."""
    branches = (node.get("config") or {}).get("branches")
    if not isinstance(branches, list) or not branches:
        return ["true", "false"]
    handles = []
    for branch in branches:
        if isinstance(branch, str):
            handles.append(branch)
        elif isinstance(branch, dict):
            handles.append(str(branch.get("handleId") or branch.get("id") or branch.get("key") or branch.get("label") or "").strip())
    return handles

class MarketplaceGraphValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid_marketplace_graph: " + ", ".join(errors))

class MarketplaceGraphValidator:
    def __init__(self, supported_node_types: set[str] | None = None): self.supported = supported_node_types or NODE_TYPES
    def validate(self, asset: dict[str, Any], *, configured_integrations: set[str] | None = None) -> None:
        graph = asset.get("graph") or {}; nodes = graph.get("nodes") or []; edges = graph.get("edges") or []; errors: list[str] = []
        keys = [n.get("key") for n in nodes]
        if len(keys) != len(set(keys)): errors.append("duplicate_node_key")
        by_key = {n.get("key"): n for n in nodes}
        starts = [n for n in nodes if n.get("type") == "start" or (n.get("config") or {}).get("isStart")]
        if len(starts) != 1: errors.append("single_start_required")
        for node in nodes:
            if node.get("type") not in self.supported: errors.append(f"unsupported_node_type:{node.get('type')}")
            if not isinstance(node.get("config"), dict): errors.append(f"missing_config:{node.get('key')}")
        outgoing = {key: [] for key in keys}
        incoming = {key: 0 for key in keys}
        for edge in edges:
            source, target = edge.get("source"), edge.get("target")
            if source not in by_key: errors.append(f"invalid_edge_source:{source}")
            if target not in by_key: errors.append(f"invalid_edge_target:{target}")
            if source in outgoing and target in by_key: outgoing[source].append(target); incoming[target] += 1
        if starts:
            reached, queue = set(), deque([starts[0].get("key")])
            while queue:
                current = queue.popleft()
                if current in reached: continue
                reached.add(current); queue.extend(outgoing.get(current, []))
            for key in set(keys) - reached: errors.append(f"unreachable_node:{key}")
        for node in nodes:
            key = node.get("key")
            if node.get("type") == "condition":
                handles = _condition_handles(node)
                condition_edges = [edge for edge in edges if edge.get("source") == key]
                edge_handles = [_edge_handle(edge, "source") for edge in condition_edges]
                if any(not handle for handle in handles): errors.append(f"condition_branch_without_handle:{key}")
                if len(handles) != len(set(handles)): errors.append(f"duplicate_condition_handle:{key}")
                for handle in handles:
                    if edge_handles.count(handle) != 1: errors.append(f"condition_handle_requires_one_edge:{key}:{handle}")
                for handle in set(edge_handles) - set(handles): errors.append(f"invalid_condition_edge_handle:{key}:{handle}")
            if node.get("type") == "choice":
                config = node.get("config") or {}
                options = config.get("buttons") if isinstance(config.get("buttons"), list) else config.get("options")
                structured_options = [option for option in (options or []) if isinstance(option, dict)]
                if structured_options:
                    handles = [str(option.get("handleId") or option.get("handle_id") or option.get("value") or option.get("id") or "").strip() for option in structured_options]
                    choice_edges = [edge for edge in edges if edge.get("source") == key]
                    edge_handles = [str(edge.get("sourceHandle", edge.get("source_handle")) or "").strip() for edge in choice_edges]
                    if any(not handle for handle in handles): errors.append(f"choice_option_without_handle:{key}")
                    if len(handles) != len(set(handles)): errors.append(f"duplicate_choice_handle:{key}")
                    for handle in handles:
                        if edge_handles.count(handle) != 1: errors.append(f"choice_handle_requires_one_edge:{key}:{handle}")
                    for handle in set(edge_handles) - set(handles): errors.append(f"invalid_choice_edge_handle:{key}:{handle}")
            if key not in {s.get("key") for s in starts} and incoming.get(key, 0) == 0: errors.append(f"orphan_node:{key}")
        # This opt-in contract is used by assets whose React Flow handles have
        # been captured from a graph authored in the editor. It prevents a
        # marketplace install from silently producing renderer-discarded edges.
        if (asset.get("metadata") or {}).get("validate_editor_handles"):
            for edge in edges:
                source_node = by_key.get(edge.get("source"))
                target_node = by_key.get(edge.get("target"))
                if not source_node or not target_node: continue
                source_handle = _edge_handle(edge, "source")
                source_type = source_node.get("type")
                if source_type in SINGLE_OUTPUT_TYPES and source_handle not in {"", "default"}:
                    errors.append(f"invalid_single_output_handle:{edge.get('source')}:{source_handle}")
                if source_type == "condition" and source_handle not in _condition_handles(source_node):
                    errors.append(f"renderer_discards_source_handle:{edge.get('source')}:{source_handle}")
            for node in nodes:
                key, node_type = node.get("key"), node.get("type")
                node_incoming = incoming.get(key, 0)
                node_outgoing = len(outgoing.get(key, []))
                if node_type == "ai_classification" and (node_incoming == 0 or node_outgoing == 0):
                    errors.append(f"ai_classification_requires_input_output:{key}")
                if node_type == "action" and (node.get("config") or {}).get("action") == "human_handoff" and (node_incoming == 0 or node_outgoing == 0):
                    errors.append(f"human_handoff_requires_input_output:{key}")
        level = (asset.get("metadata") or {}).get("automation_level")
        if level == "no_ai" and any(n.get("type") in AI_TYPES for n in nodes): errors.append("ai_node_forbidden_in_no_ai")
        declared = set(asset.get("required_integrations") or [])
        if configured_integrations is not None:
            for integration in declared - configured_integrations: errors.append(f"integration_not_configured:{integration}")
        if (asset.get("compatibility") or {}).get("runtime") != "v2": errors.append("runtime_not_supported")
        if errors: raise MarketplaceGraphValidationError(errors)

    def validate_materialized(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Reject persisted choice graphs that differ from the builder contract."""
        errors: list[str] = []
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            outgoing.setdefault(str(edge.get("source")), []).append(edge)
        for node in nodes:
            if node.get("type") != "choice":
                continue
            options = (node.get("data") or {}).get("buttons")
            if not isinstance(options, list) or not options:
                errors.append(f"choice_buttons_required:{node.get('id')}")
                continue
            ids, handles = [], []
            for option in options:
                if not isinstance(option, dict) or not all(key in option for key in ("id", "label", "value", "handleId", "next")):
                    errors.append(f"choice_option_contract_invalid:{node.get('id')}")
                    continue
                ids.append(str(option["id"]).strip()); handles.append(str(option["handleId"]).strip())
            if any(not value for value in ids): errors.append(f"choice_option_id_required:{node.get('id')}")
            if any(not value for value in handles): errors.append(f"choice_handle_required:{node.get('id')}")
            if len(ids) != len(set(ids)): errors.append(f"duplicate_choice_option_id:{node.get('id')}")
            if len(handles) != len(set(handles)): errors.append(f"duplicate_choice_handle:{node.get('id')}")
            node_edges = outgoing.get(str(node.get("id")), [])
            for handle in handles:
                matching = [edge for edge in node_edges if edge.get("sourceHandle") == handle]
                if len(matching) != 1: errors.append(f"choice_handle_requires_one_edge:{node.get('id')}:{handle}")
                for edge in matching:
                    data = edge.get("data") or {}
                    if (edge.get("targetHandle") != "default" or edge.get("type") != "default"
                            or data.get("sourceHandle") != handle):
                        errors.append(f"choice_edge_contract_invalid:{edge.get('id')}")
            for edge in node_edges:
                if edge.get("sourceHandle") not in handles:
                    errors.append(f"invalid_choice_edge_handle:{node.get('id')}:{edge.get('sourceHandle')}")
        if errors: raise MarketplaceGraphValidationError(errors)
