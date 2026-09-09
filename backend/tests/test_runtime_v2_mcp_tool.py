import inspect
import uuid
from types import SimpleNamespace

import pytest

from app.flow_v2.executors.mcp_tool_executor import MCPNodeError, MCPToolNodeExecutor, normalize_mcp_response, safe_get_path
from app.flow_v2.node_executors import EXECUTOR_REGISTRY
from app.flow_v2.template_renderer import FlowRenderContext
from app.tools.base import ToolResult


def test_mcp_tool_is_an_official_runtime_executor():
    assert "mcp_tool" in EXECUTOR_REGISTRY


def test_normalize_prefers_structured_content():
    normalized = normalize_mcp_response({"ok": True, "result": {"content": [{"type": "text", "text": "ignored"}], "structuredContent": {"result": {"slots": ["09:00"]}}}})
    assert normalized == {"ok": True, "content": [{"type": "text", "text": "ignored"}], "structured_content": {"result": {"slots": ["09:00"]}}, "is_error": False}
    assert safe_get_path(normalized["structured_content"], "result.slots") == ["09:00"]


def test_normalize_parses_serialized_json_without_executing_it():
    normalized = normalize_mcp_response({"ok": True, "result": {"content": [{"type": "text", "text": '{"appointment_id":"apt-1"}'}]}})
    assert normalized["structured_content"] == {"appointment_id": "apt-1"}


def test_safe_result_path_rejects_missing_and_dunder_segments():
    for path in ("result.missing", "__class__"):
        try:
            safe_get_path({"result": {}}, path)
        except MCPNodeError as exc:
            assert exc.code == "MCP_INVALID_RESPONSE"
        else:
            raise AssertionError("unsafe result path was accepted")


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _DB:
    def __init__(self, integration):
        self.integration = integration
        self.added = []
        self.flush_count = 0

    def execute(self, _statement):
        return _ScalarResult(self.integration)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


class _Transitions:
    def resolve(self, _db, **kwargs):
        return SimpleNamespace(target_node_id=f"after-{kwargs['source_handle']}")


class _Events:
    def __init__(self):
        self.events = []

    def append(self, _db, **kwargs):
        self.events.append(kwargs)


@pytest.fixture
def calendar_runtime(monkeypatch):
    connection_id = uuid.uuid4()
    session = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        variables={
            "appointment_period": {
                "window_start": "2026-09-08T13:00:00-03:00",
                "window_end": "2026-09-08T18:00:00-03:00",
                "timezone": "America/Sao_Paulo",
            }
        },
    )
    db = _DB(SimpleNamespace(id=connection_id))
    events = _Events()
    executor = MCPToolNodeExecutor(event_store=events, transition_resolver=_Transitions())
    monkeypatch.setattr(
        executor,
        "_render_context",
        lambda *_args, **_kwargs: FlowRenderContext(tenant_id=session.tenant_id, session=session, node_id="calendar"),
    )
    node = {
        "id": "calendar",
        "data": {
            "connection_id": f"integration:{connection_id}",
            "tool_name": "google_calendar_check_availability",
            "arguments": {
                "start": "{{appointment_period.window_start}}",
                "end": "{{appointment_period.window_end}}",
                "timezone": "{{appointment_period.timezone}}",
                "mode": "period",
            },
            "output_variable": "availability",
            "error_variable": "calendar_error",
        },
    }
    return executor, db, session, node


def test_calendar_mcp_renders_nested_arguments_and_saves_success(monkeypatch, calendar_runtime):
    executor, db, session, node = calendar_runtime
    received = {}

    def execute(_adapter, tool_name, arguments, context):
        received.update({"tool_name": tool_name, "arguments": arguments, "tenant_id": context.tenant_id})
        return ToolResult(
            ok=True,
            tool_type="google_calendar",
            output={"ok": True, "busy": []},
            structured_content={"ok": True, "result": {"busy": []}},
        )

    monkeypatch.setattr("app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute", execute)
    result = executor.execute(db, snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=SimpleNamespace())

    assert received["arguments"] == {
        "start": "2026-09-08T13:00:00-03:00",
        "end": "2026-09-08T18:00:00-03:00",
        "timezone": "America/Sao_Paulo",
        "mode": "period",
    }
    assert result.next_source_handle == "success"
    assert result.next_node_id == "after-success"
    assert session.variables["availability"] == {"ok": True, "busy": []}
    assert session.variables["appointment_period"]["window_start"] == "2026-09-08T13:00:00-03:00"


def test_calendar_mcp_tool_result_error_returns_error_handle_without_raising(monkeypatch, calendar_runtime):
    executor, db, session, node = calendar_runtime

    monkeypatch.setattr(
        "app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute",
        lambda *_args, **_kwargs: ToolResult(
            ok=False,
            tool_type="google_calendar",
            output={"ok": False, "message": "Google Calendar recusou o período."},
            error_code="google_calendar_error",
        ),
    )
    result = executor.execute(db, snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=SimpleNamespace())

    assert result.next_source_handle == "error"
    assert result.next_node_id == "after-error"
    assert session.variables["calendar_error"] == {
        "code": "google_calendar_error",
        "message": "Google Calendar recusou o período.",
        "retryable": True,
    }
    assert "availability" not in session.variables
    assert session.variables["appointment_period"]["window_end"] == "2026-09-08T18:00:00-03:00"


def test_calendar_write_is_blocked_without_explicit_external_write_authorization(monkeypatch, calendar_runtime):
    executor, db, session, node = calendar_runtime
    node["data"].update({
        "tool_name": "google_calendar_create_event",
        "tool_classification": "WRITE",
        "allow_external_write": False,
        "arguments": {
            "start": "2026-09-10T15:30:00-03:00",
            "end": "2026-09-10T16:00:00-03:00",
        },
    })
    monkeypatch.setattr(
        "app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("adapter must not run")),
    )

    result = executor.execute(db, snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=SimpleNamespace())

    assert result.next_source_handle == "error"
    assert session.variables["calendar_error"]["code"] == "MCP_CONNECTION_UNAUTHORIZED"


def test_calendar_write_runs_with_explicit_external_write_authorization(monkeypatch, calendar_runtime):
    executor, db, session, node = calendar_runtime
    node["data"].update({
        "tool_name": "google_calendar_create_event",
        "tool_classification": "WRITE",
        "allow_external_write": True,
        "arguments": {
            "start": "2026-09-10T15:30:00-03:00",
            "end": "2026-09-10T16:00:00-03:00",
        },
    })
    calls = []

    def execute(_adapter, tool_name, arguments, context):
        calls.append((tool_name, arguments, context.tenant_id))
        return ToolResult(ok=True, tool_type="google_calendar", output={"ok": True, "event_id": "event-1"})

    monkeypatch.setattr("app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute", execute)

    result = executor.execute(db, snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=SimpleNamespace())

    assert result.next_source_handle == "success"
    assert calls == [("google_calendar_create_event", node["data"]["arguments"], session.tenant_id)]


def test_calendar_destructive_tool_requires_separate_confirmation(monkeypatch, calendar_runtime):
    executor, db, session, node = calendar_runtime
    node["data"].update({
        "tool_name": "google_calendar_delete_event",
        "tool_classification": "DESTRUCTIVE",
        "allow_external_write": True,
        "destructive_confirmed": False,
        "arguments": {"event_id": "event-1"},
    })
    monkeypatch.setattr(
        "app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("adapter must not run")),
    )

    result = executor.execute(db, snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=SimpleNamespace())

    assert result.next_source_handle == "error"
    assert session.variables["calendar_error"] == {
        "code": "MCP_CONNECTION_UNAUTHORIZED",
        "message": "A ação destrutiva exige confirmação explícita.",
        "retryable": False,
    }


def test_runtime_v2_mcp_executor_uses_only_canonical_tool_result_ok():
    source = inspect.getsource(MCPToolNodeExecutor.execute)
    assert "result.ok" in source
    assert "result.success" not in source
