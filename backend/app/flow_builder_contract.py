"""Canonical persisted graph factory used by the Flow Builder and importers.

This module describes the *saved* canvas contract (callbacks and transient UI
flags are deliberately not persisted).  Code which creates a graph without an
interactive canvas must go through these functions instead of approximating
React Flow payloads.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Iterable


def _id() -> str:
    return str(uuid.uuid4())


def choice_handle(value: Any, fallback: str) -> str:
    value = re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", str(value).lower().strip()))
    return value or fallback


def create_choice_buttons(node_id: str, options: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the same defaults as ``normalizeChoiceButtons`` in the editor."""
    result = []
    for index, raw in enumerate(options):
        number = index + 1
        label = raw.get("label") or raw.get("value") or f"Opção {number}"
        value = raw.get("value") or raw.get("label") or raw.get("id") or label
        result.append({
            "id": raw.get("id") or f"{node_id}-button-{number}",
            "label": label,
            "value": value,
            "handleId": choice_handle(raw.get("handleId") or value, f"option_{number}"),
            "next": raw.get("next") or "",
        })
    return result


def create_choice_node(*, node_id: str | None = None, position: dict[str, Any] | None = None,
                       data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create exactly the node persisted after the editor's Add Choice action."""
    node_id = node_id or _id()
    overrides = dict(data or {})
    raw_buttons = overrides.pop("buttons", None)
    node_data = {
        "label": "Escolha",
        "content": "",
        "display_mode": "buttons",
        "buttons": create_choice_buttons(node_id, raw_buttons or [
            {"id": "choice-1", "label": "Quero planos", "handleId": "quero_planos"},
            {"id": "choice-2", "label": "Falar com humano", "handleId": "falar_com_humano"},
        ]),
        **overrides,
    }
    # serializeFlowGraph always persists the boolean, including false.
    node_data["isStart"] = bool(node_data.get("isStart"))
    return {"id": node_id, "type": "choice", "position": position or {"x": 0, "y": 0}, "data": node_data}


def create_edge(*, source: str, target: str, source_handle: str | None = None,
                target_handle: str | None = None, edge_id: str | None = None,
                edge_type: str = "default", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create the persisted form produced by onConnect + serializeFlowGraph."""
    handle = source_handle or "default"
    label = handle
    edge = {
        "id": edge_id or _id(), "source": source, "target": target,
        "sourceHandle": handle, "targetHandle": target_handle or "default",
        "type": edge_type, "label": label,
        "data": {"condition": label, "sourceHandle": handle},
    }
    if extra:
        edge.update(extra)
        edge["data"] = {"condition": label, "sourceHandle": handle, **(extra.get("data") or {})}
    return edge
