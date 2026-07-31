"""Canonical edge-handle contract for Data Collection nodes."""
from __future__ import annotations

from typing import Any

SUCCESS = "success"
INVALID = "invalid"
CANCEL = "cancel"
TIMEOUT = "timeout"
HANDLES = frozenset({SUCCESS, INVALID, CANCEL, TIMEOUT})
LEGACY_ALIASES = {"retry_exhausted": INVALID}


def normalize_data_collection_handle(value: Any) -> str:
    handle = str(value or "").strip().lower()
    return LEGACY_ALIASES.get(handle, handle)


def normalize_data_collection_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Migrate explicit legacy handles without guessing a missing connection."""
    collection_ids = {
        str(node.get("id")) for node in nodes
        if isinstance(node, dict) and str(node.get("type") or (node.get("data") or {}).get("type") or "").lower() == "data_collection"
    }
    normalized: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict) or str(edge.get("source")) not in collection_ids:
            normalized.append(edge)
            continue
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        raw = edge.get("sourceHandle", edge.get("source_handle"))
        if raw is None:
            raw = data.get("sourceHandle", data.get("source_handle"))
        handle = normalize_data_collection_handle(raw)
        if not handle:
            normalized.append(edge)
            continue
        normalized.append({**edge, "sourceHandle": handle, "data": {**data, "sourceHandle": handle}})
    return normalized
