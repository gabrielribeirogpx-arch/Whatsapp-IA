from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.debugger.execution_replay_service import build_execution_replay, get_execution_path


BASE = datetime(2026, 6, 19, 12, 0, 0)


class FakeDb:
    def __init__(self, rows):
        self._rows = rows


def row(offset_ms: int, event_type: str, node_id: str | None = None, duration_ms: int | None = None, **metadata):
    if node_id:
        metadata.setdefault("node_id", node_id)
    return SimpleNamespace(
        trace_id="trace-1",
        execution_id="exec-1",
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        contact_id="contact-1",
        flow_id="flow-1",
        event_type=event_type,
        timestamp=BASE + timedelta(milliseconds=offset_ms),
        created_at=BASE + timedelta(milliseconds=offset_ms),
        duration_ms=duration_ms,
        metadata_json=metadata,
    )


def test_simple_replay_builds_timeline_nodes_and_path():
    replay = build_execution_replay(FakeDb([
        row(0, "FLOW_SELECTED"),
        row(100, "NODE_EXECUTED", "node_1", 100, node_name="Start", node_type="message"),
        row(250, "NODE_EXECUTED", "node_2", 150, node_name="End", node_type="message"),
    ]), "trace-1")

    assert replay.flow_id == "flow-1"
    assert replay.conversation_id == "conversation-1"
    assert replay.duration_ms == 250
    assert [node.node_id for node in replay.nodes] == ["node_1", "node_2"]
    assert [(edge.source, edge.target) for edge in replay.edges] == [("node_1", "node_2")]
    assert get_execution_path(FakeDb([]), "missing") == []


def test_replay_with_branches_highlights_actual_order_only():
    replay = build_execution_replay(FakeDb([
        row(100, "NODE_EXECUTED", "node_1", 80),
        row(200, "NODE_EXECUTED", "node_2", 40),
        row(300, "NODE_EXECUTED", "node_5", 70),
        row(500, "NODE_EXECUTED", "node_7", 120),
    ]), "trace-1")

    assert get_execution_path(FakeDb([
        row(100, "NODE_EXECUTED", "node_1", 80),
        row(200, "NODE_EXECUTED", "node_2", 40),
        row(300, "NODE_EXECUTED", "node_5", 70),
        row(500, "NODE_EXECUTED", "node_7", 120),
    ]), "trace-1") == ["node_1", "node_2", "node_5", "node_7"]
    assert [(edge.source, edge.target) for edge in replay.edges] == [("node_1", "node_2"), ("node_2", "node_5"), ("node_5", "node_7")]
    assert all(edge.highlighted for edge in replay.edges)


def test_replay_marks_failed_node_and_associates_failure_event():
    replay = build_execution_replay(FakeDb([
        row(100, "NODE_EXECUTED", "node_1", 100),
        row(180, "NODE_FAILED", "node_1", error="boom"),
        row(190, "MESSAGE_FAILED", "node_1", provider="meta"),
    ]), "trace-1")

    assert replay.nodes[0].status == "failed"
    assert [event.event_type for event in replay.nodes[0].events] == ["NODE_EXECUTED", "NODE_FAILED", "MESSAGE_FAILED"]


def test_replay_associates_tool_call_events_to_node():
    replay = build_execution_replay(FakeDb([
        row(100, "NODE_EXECUTED", "tool_node", 50, node_type="tool"),
        row(120, "TOOL_CALLED", "tool_node", tool_name="crm.lookup"),
        row(160, "TOOL_FINISHED", "tool_node", duration_ms=40),
    ]), "trace-1")

    assert [event.event_type for event in replay.nodes[0].events] == ["NODE_EXECUTED", "TOOL_CALLED", "TOOL_FINISHED"]


def test_replay_associates_llm_events_to_node():
    replay = build_execution_replay(FakeDb([
        row(100, "NODE_EXECUTED", "ai_node", 90, node_type="ai"),
        row(110, "AI_AGENT_STARTED", "ai_node"),
        row(130, "LLM_REQUEST", "ai_node", model="gpt"),
        row(180, "LLM_RESPONSE", "ai_node", duration_ms=50),
    ]), "trace-1")

    assert [event.event_type for event in replay.nodes[0].events] == ["NODE_EXECUTED", "AI_AGENT_STARTED", "LLM_REQUEST", "LLM_RESPONSE"]
