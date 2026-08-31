import inspect
import uuid
from types import SimpleNamespace

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.executors.mcp_tool_executor import MCPNodeError, MCPToolNodeExecutor, normalize_mcp_response, safe_get_path
from app.flow_v2.node_executors import EXECUTOR_REGISTRY
from app.flow_v2.publisher import _snapshot_payload
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


def test_executor_uses_canonical_tool_result_ok_contract():
    source = inspect.getsource(MCPToolNodeExecutor)
    assert "result.ok" in source
    assert "result.success" not in source


def test_data_collection_custom_prompt_round_trips_into_snapshot_and_legacy_is_compatible():
    custom = _snapshot_payload(
        nodes=[{"id":"collect", "type":"data_collection", "data":{"prompt":"Qual período você prefere?", "variable_name":"appointment_period", "data_type":"appointment_period", "isStart":True}}],
        edges=[], start_node_id="collect",
    )
    assert custom["nodes"][0]["data"]["prompt"] == "Qual período você prefere?"
    legacy = _snapshot_payload(
        nodes=[{"id":"collect", "type":"data_collection", "data":{"variable_name":"name", "data_type":"text", "isStart":True}}],
        edges=[], start_node_id="collect",
    )
    assert "prompt" not in legacy["nodes"][0]["data"]


def test_failed_calendar_tool_result_follows_error_edge_without_crashing(monkeypatch):
    tenant_id, connection_id = uuid.uuid4(), uuid.uuid4()
    integration = SimpleNamespace(id=connection_id, tenant_id=tenant_id, provider="google_calendar", status="active")
    class Scalars:
        def first(self): return integration
    class Db:
        def execute(self, statement): return SimpleNamespace(scalars=lambda: Scalars())
        def add(self, value): pass
        def flush(self): pass
    class Executor(MCPToolNodeExecutor):
        def _render(self, value, *args, **kwargs): return value
    class Resolver:
        def __init__(self): self.handle = None
        def resolve(self, db, **kwargs):
            self.handle = kwargs["source_handle"]
            return SimpleNamespace(target_node_id="error-node")
    class Events:
        def append(self, *args, **kwargs): pass
    monkeypatch.setattr(
        "app.flow_v2.executors.mcp_tool_executor.GoogleCalendarToolAdapter.execute",
        lambda *args, **kwargs: ToolResult(False, "google_calendar", error_code="google_calendar_error"),
    )
    resolver = Resolver()
    session = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, variables={}, context={}, flow_version_id=uuid.uuid4())
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=session.flow_version_id, external_user_id="5511")
    node = {"id":"availability", "data": {"connection_id":f"integration:{connection_id}", "tool_name":"calendar.get_availability", "arguments":{"start":"2026-09-01T13:00:00-03:00", "end":"2026-09-01T18:00:00-03:00", "timezone":"America/Sao_Paulo"}, "output_variable":"slots"}}
    result = Executor(event_store=Events(), transition_resolver=resolver).execute(Db(), snapshot=SimpleNamespace(flow_id=uuid.uuid4()), session=session, node=node, runtime_input=runtime_input)
    assert result.next_node_id == "error-node"
    assert result.next_source_handle == "error"
    assert resolver.handle == "error"
    assert session.variables["mcp_error"]["code"] == "google_calendar_error"
