<<<<<<< HEAD
from __future__ import annotations

=======
"""Canonical publisher/runtime handle contract for Flow Builder nodes."""
from __future__ import annotations

import re
>>>>>>> origin/main
from typing import Any

LEGACY_HANDLE_ALIASES = {"sucesso": "success", "erro": "error", "tempo_esgotado": "timeout"}


def normalize_handle(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return LEGACY_HANDLE_ALIASES.get(normalized, normalized)


<<<<<<< HEAD
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
=======
def _option_handle(value: Any, fallback: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", str(value or "").strip().lower())) or fallback


def get_node_handle_contract(node: dict[str, Any]) -> dict[str, list[str]]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str(node.get("type") or data.get("type") or "message").strip().lower()
    sources = ["default"]
    if node_type == "mcp_tool":
        sources = ["success", "error", "timeout"]
    elif node_type == "choice_dynamic" or (node_type == "choice" and data.get("options_mode") == "dynamic"):
        sources = ["selected"]
    elif node_type == "data_collection":
        sources = ["success", "cancel", "timeout", "invalid"]
    elif node_type == "condition":
        sources = ["true", "false"]
    elif node_type == "choice":
        options = data.get("buttons") or data.get("options") or node.get("options") or []
        sources = [_option_handle(option.get("handleId") or option.get("handle_id") or option.get("value") or option.get("id") or option.get("label"), f"option_{index + 1}") for index, option in enumerate(options) if isinstance(option, dict)]
    elif node_type == "action" and isinstance(data.get("source_handles"), list) and data["source_handles"]:
        sources = [str(handle) for handle in data["source_handles"]]
    return {"sourceHandles": sources, "targetHandles": ["default"]}


def migrate_edge_handles(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite legacy aliases at the load/save boundary without changing branch semantics."""
    migrated = []
    for original in edges:
        edge = dict(original)
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        source_raw = edge.get("sourceHandle", data.get("sourceHandle", data.get("source_handle")))
        target_raw = edge.get("targetHandle", data.get("targetHandle", data.get("target_handle")))
        if source_raw not in (None, ""):
            edge["sourceHandle"] = normalize_handle(source_raw)
        if target_raw not in (None, ""):
            edge["targetHandle"] = normalize_handle(target_raw)
        migrated.append(edge)
    return migrated
>>>>>>> origin/main
