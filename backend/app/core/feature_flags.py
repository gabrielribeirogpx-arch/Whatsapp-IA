from __future__ import annotations

import os
from typing import Any


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def google_sheets_integration_enabled() -> bool:
    return _env_flag("ENABLE_GOOGLE_SHEETS_INTEGRATION", default=False)


_GOOGLE_SHEETS_TOOL_TERMS = (
    "google sheets",
    "google_sheets",
    "sheets",
    "spreadsheet",
    "planilha",
    "planilhas",
)


def is_google_sheets_tool_payload(tool: dict[str, Any]) -> bool:
    metadata = tool.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    values = [
        metadata.get("provider"),
        tool.get("id"),
        tool.get("tool_id"),
        tool.get("tool_name"),
        tool.get("display_name"),
        tool.get("name"),
        tool.get("description"),
        tool.get("server_name"),
    ]
    haystack = " ".join(str(value).lower() for value in values if value is not None)
    return any(term in haystack for term in _GOOGLE_SHEETS_TOOL_TERMS)


def filter_google_sheets_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if google_sheets_integration_enabled():
        return tools
    return [tool for tool in tools if not is_google_sheets_tool_payload(tool)]
