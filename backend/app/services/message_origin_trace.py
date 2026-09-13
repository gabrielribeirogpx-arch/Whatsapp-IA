from __future__ import annotations

import inspect
import logging
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _coalesce(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return "unknown"


def log_message_origin_trace(
    *,
    executor: Any = None,
    flow_id: Any = None,
    node_id: Any = None,
    node_type: Any = None,
    message: Any = None,
    context: dict[str, Any] | None = None,
    source_file: str | None = None,
    source_function: str | None = None,
    include_stack: bool = False,
) -> None:
    """Log a normalized trace for every WhatsApp outbound message emitter."""
    context = context or {}
    caller = inspect.stack()[1]
    resolved_file = source_file or str(Path(caller.filename))
    resolved_function = source_function or caller.function
    resolved_executor = _coalesce(
        executor,
        context.get("flow_executor"),
        context.get("executor"),
        context.get("flow_send_source"),
    )
    resolved_flow_id = _coalesce(flow_id, context.get("flow_id"))
    resolved_node_id = _coalesce(node_id, context.get("node_id"))
    resolved_node_type = _coalesce(node_type, context.get("node_type"))
    message_value = message or context.get("text") or context.get("body_text") or context.get("message") or ""
    logger.info(
        "[MESSAGE ORIGIN TRACE] executor=%s flow_id=%s node_id=%s node_type=%s source_file=%s source_function=%s message_len=%s stack_included=%s",
        resolved_executor,
        resolved_flow_id,
        resolved_node_id,
        resolved_node_type,
        resolved_file,
        resolved_function,
        len(str(message_value)),
        bool(include_stack),
    )
    if include_stack:
        logger.debug("[MESSAGE ORIGIN DIAGNOSTIC STACK] stack=%s", "".join(traceback.format_stack()))
