from __future__ import annotations
from collections import deque
from typing import Any
from .catalog import NODE_TYPES

AI_TYPES = {"ai_rag", "ai_response", "ai_classification", "ai_extraction", "ai_summary", "ai_agent", "ai_supervisor", "ai_system"}

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
            if node.get("type") == "condition" and not outgoing.get(key): errors.append(f"condition_without_output:{key}")
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
        level = (asset.get("metadata") or {}).get("automation_level")
        if level == "no_ai" and any(n.get("type") in AI_TYPES for n in nodes): errors.append("ai_node_forbidden_in_no_ai")
        declared = set(asset.get("required_integrations") or [])
        if configured_integrations is not None:
            for integration in declared - configured_integrations: errors.append(f"integration_not_configured:{integration}")
        if (asset.get("compatibility") or {}).get("runtime") != "v2": errors.append("runtime_not_supported")
        if errors: raise MarketplaceGraphValidationError(errors)
