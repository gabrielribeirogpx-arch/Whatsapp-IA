from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.debugger.execution_graph_builder import ExecutionGraphBuilder
from app.debugger.execution_serializer import ReplayEvent, ReplayExecution, ReplayNode, serialize_datetime

NODE_CONTEXT_EVENTS = {
    "NODE_FAILED", "MESSAGE_SENT", "MESSAGE_FAILED", "TOOL_CALLED", "TOOL_FINISHED",
    "MCP_DISCOVERY_STARTED", "MCP_DISCOVERY_FINISHED", "MCP_CALLED", "MCP_FINISHED", "AI_AGENT_STARTED", "LLM_REQUEST", "LLM_RESPONSE",
}


def _load_rows(db: "Session", trace_id: str) -> list[Any]:
    if hasattr(db, "_rows"):
        rows = [row for row in getattr(db, "_rows") if str(getattr(row, "trace_id", trace_id)) == str(trace_id)]
        return sorted(rows, key=lambda row: (getattr(row, "timestamp", None) or datetime.min, getattr(row, "created_at", None) or datetime.min))
    from sqlalchemy import select
    from app.models.execution_trace import ExecutionTrace

    return list(
        db.execute(
            select(ExecutionTrace)
            .where(ExecutionTrace.trace_id == str(trace_id))
            .order_by(ExecutionTrace.timestamp.asc(), ExecutionTrace.created_at.asc())
        ).scalars()
    )


def _string_id(value: Any) -> str | None:
    return None if value is None else str(value)


def _metadata(row: Any) -> dict[str, Any]:
    return dict(getattr(row, "metadata_json", None) or {})


def _node_id(row: Any) -> str | None:
    metadata = _metadata(row)
    for key in ("node_id", "node", "current_node_id"):
        if metadata.get(key) is not None:
            return str(metadata[key])
    return None


def _node_name(row: Any) -> str | None:
    metadata = _metadata(row)
    value = metadata.get("node_name") or metadata.get("name") or metadata.get("label")
    return str(value) if value is not None else None


def _node_type(row: Any) -> str | None:
    metadata = _metadata(row)
    value = metadata.get("node_type") or metadata.get("type")
    return str(value) if value is not None else None


def _event(row: Any) -> ReplayEvent:
    return ReplayEvent(
        event_type=str(getattr(row, "event_type")),
        timestamp=serialize_datetime(getattr(row, "timestamp", None)),
        execution_id=_string_id(getattr(row, "execution_id", None)),
        node_id=_node_id(row),
        duration_ms=getattr(row, "duration_ms", None),
        metadata=_metadata(row),
    )


def build_execution_replay(db: "Session", trace_id: str) -> ReplayExecution:
    rows = _load_rows(db, trace_id)
    timeline = [_event(row) for row in rows]
    executions: dict[str, list[ReplayEvent]] = defaultdict(list)
    for event in timeline:
        executions[event.execution_id or "unknown"].append(event)

    started = getattr(rows[0], "timestamp", None) if rows else None
    ended = getattr(rows[-1], "timestamp", None) if rows else None
    nodes: list[ReplayNode] = []
    node_by_key: dict[tuple[str | None, str], ReplayNode] = {}

    for row, event in zip(rows, timeline):
        event_type = str(getattr(row, "event_type"))
        node_id = event.node_id
        execution_id = event.execution_id
        if event_type == "NODE_EXECUTED" and node_id:
            completed_at = getattr(row, "timestamp", None)
            duration = getattr(row, "duration_ms", None)
            started_at = None
            if completed_at and duration is not None:
                from datetime import timedelta
                started_at = completed_at - timedelta(milliseconds=duration)
            node = ReplayNode(
                node_id=node_id,
                node_name=_node_name(row) or node_id,
                node_type=_node_type(row),
                started_at=serialize_datetime(started_at or completed_at),
                completed_at=serialize_datetime(completed_at),
                duration_ms=duration,
                status=str(_metadata(row).get("status") or "completed"),
                execution_id=execution_id,
                events=[event],
            )
            nodes.append(node)
            node_by_key[(execution_id, node_id)] = node
        elif event_type in NODE_CONTEXT_EVENTS and node_id:
            node = node_by_key.get((execution_id, node_id))
            if node is None:
                node = ReplayNode(node_id=node_id, node_name=node_id, started_at=event.timestamp, completed_at=event.timestamp, execution_id=execution_id, status="failed" if event_type.endswith("FAILED") else "running")
                nodes.append(node)
                node_by_key[(execution_id, node_id)] = node
            node.events.append(event)
            if event_type in {"NODE_FAILED", "MESSAGE_FAILED"}:
                node.status = "failed"
                node.completed_at = event.timestamp

    graph = ExecutionGraphBuilder().build(nodes, timeline)
    execution_ids = list(dict.fromkeys([event.execution_id for event in timeline if event.execution_id]))
    first = rows[0] if rows else None
    return ReplayExecution(
        trace_id=str(trace_id),
        flow_id=_string_id(getattr(first, "flow_id", None)) if first else None,
        conversation_id=_string_id(getattr(first, "conversation_id", None)) if first else None,
        contact_id=_string_id(getattr(first, "contact_id", None)) if first else None,
        tenant_id=_string_id(getattr(first, "tenant_id", None)) if first else None,
        start_time=serialize_datetime(started),
        end_time=serialize_datetime(ended),
        duration_ms=int((ended - started).total_seconds() * 1000) if started and ended else 0,
        execution_ids=execution_ids,
        nodes=graph["nodes"],
        edges=graph["edges"],
        timeline=graph["timeline"],
        executions=dict(executions),
    )


def get_execution_path(db: "Session", trace_id: str) -> list[str]:
    return ExecutionGraphBuilder().get_execution_path(build_execution_replay(db, trace_id).nodes)
