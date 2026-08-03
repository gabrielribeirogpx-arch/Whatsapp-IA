from app.flow_v2.executors.mcp_tool_executor import MCPNodeError, normalize_mcp_response, safe_get_path
from app.flow_v2.node_executors import EXECUTOR_REGISTRY


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
