import pytest

from app.flow_v2.node_executors import EXECUTOR_REGISTRY, NodeExecutorRegistry
from app.flow_v2.transition_resolver import TransitionResolver


class _NoopEventStore:
    pass


EXPECTED_NODE_TYPES = {
    "message",
    "choice",
    "delay",
    "condition",
    "action",
    "media",
    "cta_url",
    "cta_link",
    "ai_rag",
    "ai_response",
    "ai_agent",
    "ai_dispatcher",
    "ai_greeting",
    "ai_calendar_agent",
    "ai_safe_fallback",
    "ai_supervisor",
    "ai_classification",
    "ai_extraction",
    "ai_summary",
}


def test_all_runtime_v2_node_types_are_registered():
    assert EXPECTED_NODE_TYPES <= set(EXECUTOR_REGISTRY)


def test_dispatcher_resolves_registered_executor():
    registry = NodeExecutorRegistry(
        event_store=_NoopEventStore(),
        transition_resolver=TransitionResolver(_NoopEventStore()),
    )

    assert registry.get("message").__class__ is EXECUTOR_REGISTRY["message"]
    assert registry.get("cta_link").__class__ is EXECUTOR_REGISTRY["cta_link"]


def test_dispatcher_rejects_invalid_node_type_with_controlled_error():
    registry = NodeExecutorRegistry(
        event_store=_NoopEventStore(),
        transition_resolver=TransitionResolver(_NoopEventStore()),
    )

    with pytest.raises(RuntimeError, match="Unsupported Runtime V2 node type: invalid"):
        registry.get("invalid")
