"""Canonical registry for native Flow V2 canvas node types.

Keep publish/compiler allow-lists derived from this registry.  Runtime executor
implementations remain registered in ``node_executors`` because importing them
here would create a dependency cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeNodeType:
    """Capabilities shared by the Flow V2 persistence and publish pipeline."""

    executable: bool = True
    migratable: bool = True


NATIVE_NODE_REGISTRY: dict[str, NativeNodeType] = {
    "message": NativeNodeType(),
    "data_collection": NativeNodeType(),
    "choice": NativeNodeType(),
    "condition": NativeNodeType(),
    "delay": NativeNodeType(),
    "action": NativeNodeType(),
    "mcp_tool": NativeNodeType(),
    "media": NativeNodeType(),
    "cta_url": NativeNodeType(),
    "ai_rag": NativeNodeType(),
    "ai_response": NativeNodeType(),
    "ai_classification": NativeNodeType(),
    "ai_extraction": NativeNodeType(),
    "ai_summary": NativeNodeType(),
    "ai_agent": NativeNodeType(),
    "ai_supervisor": NativeNodeType(),
    "ai_system": NativeNodeType(),
    # ``start`` is an accepted persisted marker, not an executable node.
    "start": NativeNodeType(executable=False, migratable=False),
}

PUBLISHABLE_NODE_TYPES: frozenset[str] = frozenset(NATIVE_NODE_REGISTRY)
MIGRATABLE_NODE_TYPES: frozenset[str] = frozenset(
    node_type
    for node_type, capabilities in NATIVE_NODE_REGISTRY.items()
    if capabilities.migratable
)
EXECUTABLE_NATIVE_NODE_TYPES: frozenset[str] = frozenset(
    node_type
    for node_type, capabilities in NATIVE_NODE_REGISTRY.items()
    if capabilities.executable
)
