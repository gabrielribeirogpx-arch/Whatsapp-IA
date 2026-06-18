from datetime import UTC, datetime, timedelta

import pytest

from app.services.execution_budget_service import ExecutionBudget, ExecutionBudgetExceeded


def _budget(**overrides):
    data = {"execution_id": "e1", "tenant_id": "t1", "started_at": datetime.now(UTC)}
    data.update(overrides)
    return ExecutionBudget(**data)


def test_budget_duration_exceeded():
    budget = _budget(started_at=datetime.now(UTC) - timedelta(seconds=2), max_duration_ms=1)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.checkpoint("test")
    assert budget.safe_metadata()["budget_exceeded"] is True
    assert budget.safe_metadata()["budget_exceeded_reason"] == "duration"


def test_budget_llm_calls_exceeded():
    budget = _budget(max_llm_calls=1)
    budget.consume_llm_call(prompt_tokens_estimate=1)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.consume_llm_call(prompt_tokens_estimate=1)


def test_budget_mcp_calls_exceeded():
    budget = _budget(max_mcp_calls=0)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.consume_mcp_call()


def test_budget_webhook_calls_exceeded():
    budget = _budget(max_webhook_calls=0)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.consume_webhook_call()


def test_budget_subflow_calls_exceeded():
    budget = _budget(max_subflow_calls=0)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.consume_subflow_call()


def test_budget_node_tool_calls_exceeded():
    budget = _budget(max_node_tool_calls=0)
    with pytest.raises(ExecutionBudgetExceeded):
        budget.consume_node_tool_call()


def test_budget_metadata_roundtrip_and_child_reuses_same_budget():
    budget = _budget(max_llm_calls=2)
    metadata = budget.to_metadata()
    restored = ExecutionBudget.from_metadata(metadata, tenant_id="t1")
    restored.consume_llm_call()
    child = restored.clone_for_child()
    assert child is restored
    assert child.llm_calls_used == 1


def test_safe_metadata_has_playground_keys_without_prompt():
    budget = _budget()
    budget.consume_tokens(prompt=10, completion=2, estimated=True)
    meta = budget.safe_metadata()
    assert meta["execution_budget_enabled"] is True
    assert meta["budget_prompt_tokens_used"] == 10
    assert meta["budget_tokens_estimated"] is True
    assert "prompt" not in meta
