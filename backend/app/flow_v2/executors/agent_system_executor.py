"""Specialized agent-system template executors."""
from app.flow_v2.executors._legacy import (
    AiCalendarAgentNodeExecutor,
    AiDispatcherNodeExecutor,
    AiGreetingNodeExecutor,
    AiSafeFallbackNodeExecutor,
)

__all__ = [
    "AiDispatcherNodeExecutor",
    "AiGreetingNodeExecutor",
    "AiCalendarAgentNodeExecutor",
    "AiSafeFallbackNodeExecutor",
]
