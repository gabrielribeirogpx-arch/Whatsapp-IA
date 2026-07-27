from __future__ import annotations

import json
import logging
from typing import Any, Mapping


TRACE_FIELDS = (
    "correlation_id", "conversation_id", "session_id", "flow_id", "flow_version_id",
    "message.type", "interactive.type", "button_reply.id", "button_reply.title",
    "interactive_reply_id", "selected_row_id", "row_id", "runtime_choice_key", "sourceHandle",
    "current_node_id", "waiting_for_choice", "current_wait_node", "matched_option_id",
    "matched_source_handle", "next_node_id", "executor_step", "transition_found",
    "node_executed", "message_sent",
)


def runtime_trace(logger: logging.Logger, stage: str, *, metadata: Mapping[str, Any] | None = None, **values: Any) -> None:
    """Emit one complete, machine-searchable record without affecting runtime flow."""
    source = dict(metadata or {})
    aliases = {
        "correlation_id": source.get("correlation_id") or source.get("input_message_id") or source.get("message_id"),
        "message.type": source.get("message.type") or source.get("message_type") or source.get("type"),
        "interactive.type": source.get("interactive.type") or source.get("interactive_type"),
        "button_reply.id": source.get("button_reply.id") or source.get("button_reply_id") or source.get("interactive_reply_id"),
        "button_reply.title": source.get("button_reply.title") or source.get("button_reply_title") or source.get("interactive_reply_title"),
    }
    record = {field: values.get(field, source.get(field, aliases.get(field))) for field in TRACE_FIELDS}
    record.update({"event": values.pop("event", "runtime_trace"), "stage": stage})
    record.update(values)
    logger.info("runtime_trace=%s", json.dumps(record, default=str, ensure_ascii=False, sort_keys=True))


def runtime_exit(logger: logging.Logger, stage: str, *, reason: str, metadata: Mapping[str, Any] | None = None, **values: Any) -> None:
    runtime_trace(logger, stage, event="runtime_exit", reason=reason, metadata=metadata, **values)
