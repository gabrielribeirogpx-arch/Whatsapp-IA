from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class ExecutionBudgetExceeded(Exception):
    """Raised when a safe execution budget limit is exceeded."""


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ExecutionBudget:
    execution_id: str
    tenant_id: str
    started_at: datetime
    max_duration_ms: int = 60000
    max_runtime_steps: int = 50
    max_llm_calls: int = 10
    max_mcp_calls: int = 5
    max_webhook_calls: int = 5
    max_subflow_calls: int = 3
    max_node_tool_calls: int = 5
    max_tokens_prompt: int = 12000
    max_tokens_completion: int = 6000
    max_cost_usd: float | None = None
    max_depth: int = 5
    runtime_steps_used: int = 0
    llm_calls_used: int = 0
    mcp_calls_used: int = 0
    webhook_calls_used: int = 0
    subflow_calls_used: int = 0
    node_tool_calls_used: int = 0
    prompt_tokens_used: int = 0
    completion_tokens_used: int = 0
    estimated_cost_used: float = 0.0
    depth_used: int = 0
    exceeded_reason: str | None = None
    tokens_estimated: bool = False

    @classmethod
    def defaults(cls, tenant_id: Any, execution_id: str | None = None) -> "ExecutionBudget":
        return cls(
            execution_id=execution_id or str(uuid.uuid4()),
            tenant_id=str(tenant_id),
            started_at=_utcnow(),
            max_duration_ms=_env_int("AI_EXECUTION_MAX_DURATION_MS", 60000),
            max_llm_calls=_env_int("AI_EXECUTION_MAX_LLM_CALLS", 10),
            max_mcp_calls=_env_int("AI_EXECUTION_MAX_MCP_CALLS", 5),
            max_webhook_calls=_env_int("AI_EXECUTION_MAX_WEBHOOK_CALLS", 5),
            max_subflow_calls=_env_int("AI_EXECUTION_MAX_SUBFLOW_CALLS", 3),
            max_node_tool_calls=_env_int("AI_EXECUTION_MAX_NODE_TOOL_CALLS", 5),
            max_tokens_prompt=_env_int("AI_EXECUTION_MAX_PROMPT_TOKENS", 12000),
            max_tokens_completion=_env_int("AI_EXECUTION_MAX_COMPLETION_TOKENS", 6000),
            max_depth=_env_int("AI_EXECUTION_MAX_DEPTH", 5),
        )

    def duration_ms(self) -> int:
        return int((_utcnow() - self.started_at).total_seconds() * 1000)

    def remaining_ms(self) -> int:
        return max(0, int(self.max_duration_ms) - self.duration_ms())

    def _exceeded(self, reason: str) -> None:
        self.exceeded_reason = reason
        raise ExecutionBudgetExceeded(f"Execution budget exceeded: {reason}")

    def checkpoint(self, label: str) -> None:
        if self.duration_ms() > self.max_duration_ms:
            self._exceeded("duration")
        if self.max_cost_usd is not None and self.estimated_cost_used > self.max_cost_usd:
            self._exceeded("cost")

    def consume_runtime_step(self, count: int = 1) -> None:
        self.runtime_steps_used += max(1, int(count or 1)); self.checkpoint("runtime_step")
        if self.runtime_steps_used > self.max_runtime_steps: self._exceeded("runtime_steps")

    def consume_llm_call(self, prompt_tokens_estimate: int = 0, completion_tokens_estimate: int = 0) -> None:
        self.llm_calls_used += 1
        self.consume_tokens(prompt_tokens_estimate, completion_tokens_estimate, estimated=True)
        if self.llm_calls_used > self.max_llm_calls: self._exceeded("llm_calls")
        self.checkpoint("llm_call")

    def consume_mcp_call(self) -> None:
        self.mcp_calls_used += 1; self.checkpoint("mcp_call")
        if self.mcp_calls_used > self.max_mcp_calls: self._exceeded("mcp_calls")

    def consume_webhook_call(self) -> None:
        self.webhook_calls_used += 1; self.checkpoint("webhook_call")
        if self.webhook_calls_used > self.max_webhook_calls: self._exceeded("webhook_calls")

    def consume_subflow_call(self) -> None:
        self.subflow_calls_used += 1; self.checkpoint("subflow_call")
        if self.subflow_calls_used > self.max_subflow_calls: self._exceeded("subflow_calls")

    def consume_node_tool_call(self) -> None:
        self.node_tool_calls_used += 1; self.checkpoint("node_tool_call")
        if self.node_tool_calls_used > self.max_node_tool_calls: self._exceeded("node_tool_calls")

    def consume_tokens(self, prompt: int = 0, completion: int = 0, *, estimated: bool = False) -> None:
        self.prompt_tokens_used += max(0, int(prompt or 0)); self.completion_tokens_used += max(0, int(completion or 0))
        self.tokens_estimated = self.tokens_estimated or estimated
        if self.prompt_tokens_used > self.max_tokens_prompt: self._exceeded("prompt_tokens")
        if self.completion_tokens_used > self.max_tokens_completion: self._exceeded("completion_tokens")

    def enter_depth(self) -> None:
        self.depth_used += 1; self.checkpoint("depth")
        if self.depth_used > self.max_depth: self._exceeded("depth")

    def exit_depth(self) -> None:
        self.depth_used = max(0, self.depth_used - 1)

    def to_metadata(self) -> dict[str, Any]:
        return {"execution_budget": {**self.__dict__, "started_at": self.started_at.isoformat()}}

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None, tenant_id: Any | None = None) -> "ExecutionBudget":
        raw = (metadata or {}).get("execution_budget")
        if not isinstance(raw, dict):
            return cls.defaults(tenant_id or (metadata or {}).get("tenant_id") or "unknown")
        data = dict(raw); data["started_at"] = datetime.fromisoformat(str(data.get("started_at")))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def clone_for_child(self) -> "ExecutionBudget":
        return self

    def safe_metadata(self) -> dict[str, Any]:
        return {"execution_budget_enabled": True, "budget_exceeded": bool(self.exceeded_reason), "budget_exceeded_reason": self.exceeded_reason, "budget_runtime_steps_used": self.runtime_steps_used, "budget_llm_calls_used": self.llm_calls_used, "budget_mcp_calls_used": self.mcp_calls_used, "budget_webhook_calls_used": self.webhook_calls_used, "budget_subflow_calls_used": self.subflow_calls_used, "budget_node_tool_calls_used": self.node_tool_calls_used, "budget_prompt_tokens_used": self.prompt_tokens_used, "budget_completion_tokens_used": self.completion_tokens_used, "budget_duration_ms": self.duration_ms(), "prompt_tokens_estimated": self.prompt_tokens_used, "completion_tokens_estimated": self.completion_tokens_used, "budget_tokens_estimated": self.tokens_estimated}


def get_or_create_budget(metadata: dict[str, Any] | None, tenant_id: Any) -> ExecutionBudget:
    return ExecutionBudget.from_metadata(metadata, tenant_id)


def persist_budget(metadata: dict[str, Any] | None, budget: ExecutionBudget) -> None:
    if isinstance(metadata, dict):
        metadata.update(budget.to_metadata())
