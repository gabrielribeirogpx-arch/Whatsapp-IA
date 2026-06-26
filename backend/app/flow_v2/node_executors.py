from __future__ import annotations

"""Runtime V2 node executor dispatcher.

Concrete executors live in :mod:`app.flow_v2.executors` and are grouped by
runtime responsibility.  This module intentionally keeps the historical public
imports while limiting new logic to registry/dispatch concerns.
"""

import sys
import types
from typing import Type

from app.flow_v2.transition_resolver import TransitionResolver
from app.flow_v2.executors import (
    ActionNodeExecutor,
    AiAgentNodeExecutor,
    AiCalendarAgentNodeExecutor,
    AiDispatcherNodeExecutor,
    AiGreetingNodeExecutor,
    AiSafeFallbackNodeExecutor,
    AiClassificationNodeExecutor,
    AiExtractionNodeExecutor,
    AiRagNodeExecutor,
    AiResponseNodeExecutor,
    AiStructuredNodeExecutor,
    AiSummaryNodeExecutor,
    AiSupervisorNodeExecutor,
    BaseNodeExecutor,
    ChoiceNodeExecutor,
    ConditionNodeExecutor,
    CtaUrlNodeExecutor,
    DelayNodeExecutor,
    MediaNodeExecutor,
    MessageNodeExecutor,
    NodeExecutionResult,
    NodeExecutor,
    calculate_typing_delay_seconds,
    extract_message_text_from_node,
)
from app.flow_v2.executors import _legacy as _legacy_executors

EXECUTOR_REGISTRY: dict[str, Type[NodeExecutor]] = {}


def register_executor(node_type: str, executor: Type[NodeExecutor]) -> None:
    """Register an executor class for a Runtime V2 node type."""
    normalized_type = str(node_type or "").strip().lower()
    if not normalized_type:
        raise RuntimeError("Runtime V2 node type cannot be empty")
    EXECUTOR_REGISTRY[normalized_type] = executor


for _node_type, _executor in {
    "message": MessageNodeExecutor,
    "choice": ChoiceNodeExecutor,
    "delay": DelayNodeExecutor,
    "condition": ConditionNodeExecutor,
    "action": ActionNodeExecutor,
    "media": MediaNodeExecutor,
    "cta_url": CtaUrlNodeExecutor,
    "cta_link": CtaUrlNodeExecutor,
    "ai_rag": AiRagNodeExecutor,
    "ai_response": AiResponseNodeExecutor,
    "ai_agent": AiAgentNodeExecutor,
    "ai_dispatcher": AiDispatcherNodeExecutor,
    "ai_greeting": AiGreetingNodeExecutor,
    "ai_calendar_agent": AiCalendarAgentNodeExecutor,
    "ai_safe_fallback": AiSafeFallbackNodeExecutor,
    "ai_supervisor": AiSupervisorNodeExecutor,
    "ai_classification": AiClassificationNodeExecutor,
    "ai_extraction": AiExtractionNodeExecutor,
    "ai_summary": AiSummaryNodeExecutor,
}.items():
    register_executor(_node_type, _executor)


class NodeExecutorRegistry:
    def __init__(self, *, event_store, transition_resolver: TransitionResolver) -> None:
        self._executors: dict[str, NodeExecutor] = {
            node_type: executor(
                event_store=event_store,
                transition_resolver=transition_resolver,
            )
            for node_type, executor in EXECUTOR_REGISTRY.items()
        }

    def get(self, node_type: str) -> NodeExecutor:
        try:
            return self._executors[node_type]
        except KeyError as exc:
            raise RuntimeError(
                f"Unsupported Runtime V2 node type: {node_type}"
            ) from exc


class _NodeExecutorsModule(types.ModuleType):
    """Propagate historical monkeypatches to the extracted executor module."""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if hasattr(_legacy_executors, name):
            setattr(_legacy_executors, name, value)


sys.modules[__name__].__class__ = _NodeExecutorsModule

# Keep all historical import/monkeypatch targets available from this dispatcher.
for _name in getattr(_legacy_executors, "__dict__", {}):
    if _name.startswith("__") or _name in globals():
        continue
    globals()[_name] = getattr(_legacy_executors, _name)

__all__ = [
    "NodeExecutionResult",
    "NodeExecutor",
    "BaseNodeExecutor",
    "MessageNodeExecutor",
    "MediaNodeExecutor",
    "CtaUrlNodeExecutor",
    "ChoiceNodeExecutor",
    "DelayNodeExecutor",
    "ConditionNodeExecutor",
    "ActionNodeExecutor",
    "AiRagNodeExecutor",
    "AiResponseNodeExecutor",
    "AiAgentNodeExecutor",
    "AiDispatcherNodeExecutor",
    "AiGreetingNodeExecutor",
    "AiCalendarAgentNodeExecutor",
    "AiSafeFallbackNodeExecutor",
    "AiSupervisorNodeExecutor",
    "AiSummaryNodeExecutor",
    "AiStructuredNodeExecutor",
    "AiClassificationNodeExecutor",
    "AiExtractionNodeExecutor",
    "NodeExecutorRegistry",
    "EXECUTOR_REGISTRY",
    "register_executor",
    "extract_message_text_from_node",
    "calculate_typing_delay_seconds",
]
