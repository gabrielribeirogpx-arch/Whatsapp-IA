from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.execution_budget_service import ExecutionBudget
from app.tools import ToolContext, ToolRegistry
from app.tools.adapters.mcp_tool_adapter import MCPToolAdapter
from app.tools.adapters.node_tool_adapter import NodeToolAdapter
from app.tools.adapters.subflow_tool_adapter import SubflowToolAdapter
from app.tools.adapters.webhook_tool_adapter import WebhookToolAdapter
from app.tools.base import ToolResult
from app.tools.context import sanitize_metadata


def _budget(**kw):
    data = {"execution_id": "t", "tenant_id": "tenant", "started_at": datetime.now(UTC)}
    data.update(kw)
    return ExecutionBudget(**data)


class DummyAdapter:
    tool_type = "dummy"
    def __init__(self): self.called = False
    def can_execute(self, tool_id, input, context, config=None): return bool((config or {}).get("allow", True))
    def execute(self, tool_id, input, context, config=None):
        self.called = True
        return ToolResult(True, self.tool_type, tool_id=tool_id, output={"ok": True})


def test_registry_registers_adapters():
    adapter = DummyAdapter(); registry = ToolRegistry(); registry.register(adapter)
    assert registry.get("dummy") is adapter
    assert registry.execute("dummy", "x", {}, ToolContext(tenant_id="t")).ok is True


def test_missing_tool_returns_controlled_result():
    result = ToolRegistry().execute("missing", "x", {}, ToolContext(tenant_id="t"))
    assert result.ok is False
    assert result.error_code == "tool_not_found"


def test_tool_not_allowed_blocks_execution():
    adapter = DummyAdapter(); registry = ToolRegistry(); registry.register(adapter)
    result = registry.execute("dummy", "x", {}, ToolContext(tenant_id="t"), {"allow": False})
    assert result.ok is False
    assert result.error_code == "tool_not_allowed"
    assert adapter.called is False


def test_budget_exceeded_blocks_side_effect():
    adapter = DummyAdapter(); registry = ToolRegistry(); registry.register(adapter)
    budget = _budget(max_duration_ms=1, started_at=datetime.now(UTC) - timedelta(seconds=1))
    result = registry.execute("dummy", "x", {}, ToolContext(tenant_id="t", execution_budget=budget))
    assert result.ok is False
    assert result.error_code == "budget_exceeded"
    assert adapter.called is False


def test_node_tool_adapter_calls_existing_service():
    calls = []
    adapter = NodeToolAdapter(lambda tool, text, reason: calls.append((tool, text, reason)) or {"status": "success", "output": {"token": "secret"}, "node_type": "message"})
    result = adapter.execute("n1", "oi", ToolContext(execution_budget=_budget()), {"node_tools": [{"tool_id": "n1"}], "reason": "r", "consume_budget": False})
    assert result.ok is True
    assert calls and calls[0][0]["tool_id"] == "n1"


def test_subflow_adapter_calls_existing_service():
    adapter = SubflowToolAdapter(lambda tool, text, reason: {"status": "success", "output": {"text": text}, "flow_id": "f", "duration_ms": 1})
    assert adapter.execute("s1", "oi", ToolContext(execution_budget=_budget()), {"subflow_tools": [{"tool_id": "s1"}], "consume_budget": False}).ok is True


def test_mcp_adapter_calls_existing_service():
    adapter = MCPToolAdapter(lambda tool, args: {"ok": True, "status": "success", "result": {"x": 1}, "latency_ms": 2})
    result = adapter.execute("m1", {"a": 1}, ToolContext(), {"mcp_tools": [{"tool_id": "m1"}]})
    assert result.ok is True and result.output == {"x": 1}


def test_webhook_adapter_blocks_insecure_url():
    adapter = WebhookToolAdapter(lambda *a, **k: {"ok": True}, lambda webhook: "internal_or_invalid_url" if webhook.get("url", "").startswith("http://") else None)
    ctx = ToolContext(execution_budget=_budget())
    assert adapter.can_execute("w1", {}, ctx, {"webhooks": [{"id": "w1", "url": "http://localhost"}]}) is False


def test_metadata_is_sanitized():
    assert sanitize_metadata({"Authorization": "Bearer x", "nested": {"api_key": "k", "ok": "v"}}) == {"Authorization": "[REDACTED]", "nested": {"api_key": "[REDACTED]", "ok": "v"}}


def test_mcp_adapter_preserves_structured_content_from_result():
    structured_content = {"ok": True, "tool": "calendar_create_event", "result": {"title": "Reunião"}}
    adapter = MCPToolAdapter(lambda tool, args: {"ok": True, "status": "success", "result": {"content": [{"type": "text", "text": "ok"}], "structuredContent": structured_content}})
    result = adapter.execute("m1", {}, ToolContext(), {"mcp_tools": [{"tool_id": "m1"}]})
    assert result.ok is True
    assert result.output["structuredContent"] == structured_content
    assert result.structured_content == structured_content


def test_mcp_adapter_normalizes_structured_content_contract_for_known_and_unknown_tools():
    tool_names = [
        "calendar_create_event",
        "calendar_list_events",
        "calendar_check_availability",
        "calendar_delete_event",
        "calculate",
        "get_business_hours",
        "fake_custom_tool",
    ]

    def executor(tool, args):
        return {
            "ok": True,
            "status": "success",
            "result": {
                "structuredContent": {
                    "ok": True,
                    "tool": tool["tool_id"],
                    "type": "custom.operation" if tool["tool_id"] == "fake_custom_tool" else None,
                    "summary": "Operação realizada",
                    "data": {"foo": "bar"},
                }
            },
        }

    adapter = MCPToolAdapter(executor)
    for name in tool_names:
        result = adapter.execute(name, {}, ToolContext(), {"mcp_tools": [{"tool_id": name, "name": name}]})
        assert result.ok is True
        assert result.normalized_result is not None
        assert result.normalized_result.ok is True
        assert result.normalized_result.tool == name
        assert result.normalized_result.summary == "Operação realizada"
        assert result.normalized_result.data == {"foo": "bar"}


def test_mcp_adapter_text_fallback_without_structured_content():
    adapter = MCPToolAdapter(lambda tool, args: {"ok": True, "status": "success", "result": {"content": [{"type": "text", "text": "Texto legado"}]}})
    result = adapter.execute("legacy_tool", {}, ToolContext(), {"mcp_tools": [{"tool_id": "legacy_tool"}]})
    assert result.ok is True
    assert result.normalized_result is not None
    assert result.normalized_result.result_text == "Texto legado"
    assert result.normalized_result.data == {}
