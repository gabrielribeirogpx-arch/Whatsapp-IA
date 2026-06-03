from __future__ import annotations

import inspect
import logging
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GHOST_MESSAGE_TEXT = "Sem problemas! Posso te mostrar nossos planos."


def _preview(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


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
    include_stack: bool = True,
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
    preview = _preview(message or context.get("text") or context.get("body_text") or context.get("message"))
    stack = "".join(traceback.format_stack()) if include_stack else "disabled"
    log_method = logger.error if preview == GHOST_MESSAGE_TEXT else logger.warning
    log_method(
        "[MESSAGE ORIGIN TRACE] executor=%s flow_id=%s node_id=%s node_type=%s source_file=%s source_function=%s message_preview=%s stack=%s",
        resolved_executor,
        resolved_flow_id,
        resolved_node_id,
        resolved_node_type,
        resolved_file,
        resolved_function,
        preview,
        stack,
    )
