from __future__ import annotations

from typing import Any

LEGACY_HANDLE_ALIASES = {"sucesso": "success", "erro": "error", "tempo_esgotado": "timeout"}


def normalize_handle(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return LEGACY_HANDLE_ALIASES.get(normalized, normalized)


def canonical_node_handles(node: dict[str, Any]) -> tuple[set[str], set[str]]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str(node.get("type") or data.get("type") or "").strip().lower()
    source = {"default"}
    target = {"default"}
    if node_type == "mcp_tool":
        source = {"success", "error", "timeout"}
    elif node_type == "condition":
        source = {"true", "false"}
    elif node_type == "choice_dynamic" or (
        node_type == "choice" and str(data.get("options_mode") or data.get("option_mode") or "").lower() == "dynamic"
    ):
        source = {"default"}
    elif node_type == "choice":
        options = data.get("buttons") if isinstance(data.get("buttons"), list) else data.get("options")
        if not isinstance(options, list):
            options = node.get("options", [])
        source = set()
        for index, option in enumerate(options if isinstance(options, list) else []):
            if not isinstance(option, dict):
                continue
            raw = option.get("handleId") or option.get("handle_id") or option.get("value") or option.get("id") or option.get("label")
            handle = "".join(char for char in str(raw or "").strip().lower().replace(" ", "_") if char.isalnum() or char == "_")
            source.add(handle or f"option_{index + 1}")
    elif node_type == "data_collection":
        source = {"success", "invalid", "cancel", "timeout"}
        if data.get("auto_retry_invalid") is True and data.get("attempts_exceeded_behavior") == "end":
            source.discard("invalid")
    return source, target


def migrate_legacy_edge_handles(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for camel, snake in (("sourceHandle", "source_handle"), ("targetHandle", "target_handle")):
            raw = edge.get(camel) if edge.get(camel) is not None else edge.get(snake)
            normalized = normalize_handle(raw)
            if normalized and normalized != str(raw or "").strip().lower():
                edge[camel] = normalized
    return edges
