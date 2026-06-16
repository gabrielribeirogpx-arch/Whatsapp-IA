from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.flow_v2.actions import RuntimeAction

FLOW_V2_EVENT_VERSION = 1


class FlowV2EventType(StrEnum):
    SESSION_STARTED = "session.started"
    INPUT_RECEIVED = "input.received"
    NODE_ENTERED = "NODE_ENTERED"
    NODE_EXECUTED = "NODE_EXECUTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    TRANSITION_SELECTED = "TRANSITION_SELECTED"
    TRANSITION_NOT_FOUND = "TRANSITION_NOT_FOUND"
    TRANSITION_AMBIGUOUS = "TRANSITION_AMBIGUOUS"
    MESSAGE_SENT = "MESSAGE_SENT"
    CHOICE_SHOWN = "CHOICE_SHOWN"
    CHOICE_SELECTED = "CHOICE_SELECTED"
    DELAY_SCHEDULED = "DELAY_SCHEDULED"
    DELAY_RESUMED = "DELAY_RESUMED"
    CONDITION_EVALUATED = "CONDITION_EVALUATED"
    OUTPUT_EMITTED = "output.emitted"
    SESSION_WAITING = "session.waiting"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"


class FlowV2SessionStatus(StrEnum):
    RUNNING = "running"
    ACTIVE = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FINISHED = "completed"
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
    event_id: str | None = None
    message_id: str | None = None
    webhook_id: str | None = None
    event_version: int = FLOW_V2_EVENT_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = dict(self.metadata or {})
        choice_id = metadata.get("selected_row_id") or metadata.get("interactive_reply_id")
        if choice_id:
            if not metadata.get("row_id"):
                metadata["row_id"] = choice_id
            if not metadata.get("sourceHandle"):
                metadata["sourceHandle"] = choice_id
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class RuntimeOutput:
    session_id: UUID
    status: FlowV2SessionStatus
    current_node_id: str | None
    effects: tuple[dict[str, Any], ...] = ()
    actions: tuple[RuntimeAction, ...] = ()
    emitted_event_count: int = 0
