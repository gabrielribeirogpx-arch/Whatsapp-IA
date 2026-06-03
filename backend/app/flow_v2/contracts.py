from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class FlowV2EventType(StrEnum):
    SESSION_STARTED = "session.started"
    INPUT_RECEIVED = "input.received"
    NODE_ENTERED = "node.entered"
    NODE_COMPLETED = "node.completed"
    TRANSITION_SELECTED = "transition.selected"
    OUTPUT_EMITTED = "output.emitted"
    SESSION_WAITING = "session.waiting"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"


class FlowV2SessionStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class RuntimeInput:
    tenant_id: UUID
    flow_version_id: UUID
    external_user_id: str
    message_text: str | None = None
    contact_id: UUID | None = None
    conversation_id: UUID | None = None
    input_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeOutput:
    session_id: UUID
    status: FlowV2SessionStatus
    current_node_id: str | None
    effects: tuple[dict[str, Any], ...] = ()
    emitted_event_count: int = 0
