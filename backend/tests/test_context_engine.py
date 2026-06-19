from types import SimpleNamespace

from app.context_engine import ContextLimits, UnifiedContextEngine
from app.context_engine.context_sources import ConversationSource
from app.context_engine.sanitizer import sanitize_metadata
from app.services.execution_budget_service import ExecutionBudget


def test_unified_context_engine_minimal_build():
    package = UnifiedContextEngine(None).build(tenant_id="t1", flags={"include_short_memory": False, "include_long_memory": False, "include_rag_context": False})
    assert package.tenant_id == "t1"
    assert package.sources["tenant"]["ok"] is True


def test_unified_context_engine_complete_build_with_rag_and_metadata():
    package = UnifiedContextEngine(None).build(
        tenant=SimpleNamespace(id="t1", name="Tenant"),
        session=SimpleNamespace(id="s1", flow_version_id="fv1", context={"name": "ok", "Authorization": "secret"}),
        execution_context={"contact_id": "c1", "tool_outputs": [{"ok": True}]},
        flags={"include_short_memory": False, "include_long_memory": False, "include_rag_context": True, "source_options": {"rag": {"chunks": [{"content": "doc"}]}}},
    )
    assert package.session_id == "s1"
    assert package.rag_chunks == [{"content": "doc"}]
    assert "Authorization" not in package.session_variables


def test_unified_context_engine_source_failure_isolated(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("broken")
    monkeypatch.setattr(ConversationSource, "load", boom)
    package = UnifiedContextEngine(None).build(tenant_id="t1")
    assert package.sources["conversation"]["ok"] is False
    assert package.stats["fallback_used"] is True


def test_sanitizer_removes_secrets():
    clean = sanitize_metadata({"Authorization": "Bearer abc", "nested": {"api_key": "x", "safe": "Bearer token"}, "ok": "value"})
    assert "Authorization" not in clean
    assert "api_key" not in clean["nested"]
    assert clean["nested"]["safe"] == "[redacted]"


def test_unified_context_engine_budget_reduces_context():
    budget = ExecutionBudget.defaults("t1")
    budget.max_tokens_prompt = 20
    package = UnifiedContextEngine(None, limits=ContextLimits(max_history_messages=10, max_rag_chunks=10, max_long_memory_items=5, max_tool_outputs=5, max_context_chars=1000, max_context_tokens=1000)).build(
        tenant_id="t1",
        budget=budget,
        flags={"include_short_memory": False, "include_long_memory": False, "include_rag_context": True, "source_options": {"rag": {"chunks": [{"content": "x" * 500}, {"content": "y" * 500}]}}},
    )
    assert len(package.combined_prompt_section()) <= 80
    assert package.safe_metadata.get("context_reduced")


def test_ai_agent_service_wires_unified_context_engine():
    source = open("backend/app/services/ai_agent_service.py", encoding="utf-8").read()
    assert "UnifiedContextEngine" in source
    assert "unified_context_engine" in source


def test_supervisor_uses_unified_context_engine_through_context_builder():
    source = open("backend/app/services/supervisor_service.py", encoding="utf-8").read()
    builder = open("backend/app/services/context_builder_service.py", encoding="utf-8").read()
    assert "build_context" in source
    assert "UnifiedContextEngine" in builder
    assert "_legacy_build_context" in builder


def test_context_builder_fallback_is_preserved():
    builder = open("backend/app/services/context_builder_service.py", encoding="utf-8").read()
    assert "unified_context_engine_failed" in builder
    assert "return _legacy_build_context" in builder
