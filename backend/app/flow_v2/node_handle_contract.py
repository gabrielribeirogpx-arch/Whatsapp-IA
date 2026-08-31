"""Canonical publisher/runtime handle contract for Flow Builder nodes."""
from __future__ import annotations

import re
from typing import Any

from app.flow_v2.data_collection_handles import HANDLES as DATA_COLLECTION_HANDLES, normalize_data_collection_edges

LEGACY_HANDLE_ALIASES = {"sucesso": "success", "erro": "error", "tempo_esgotado": "timeout"}


def normalize_handle(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return LEGACY_HANDLE_ALIASES.get(normalized, normalized)


def _option_handle(value: Any, fallback: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", str(value or "").strip().lower())) or fallback


def get_node_handle_contract(node: dict[str, Any]) -> dict[str, list[str]]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str(node.get("type") or data.get("type") or "message").strip().lower()
    sources = ["default"]
    if node_type == "mcp_tool":
        sources = ["success", "error", "timeout"]
    elif node_type == "choice_dynamic" or (node_type == "choice" and data.get("options_mode") == "dynamic"):
        sources = ["selected", "empty"]
    elif node_type == "data_collection":
        sources = list(DATA_COLLECTION_HANDLES)
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
    for original in normalize_data_collection_edges(nodes, edges):
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
