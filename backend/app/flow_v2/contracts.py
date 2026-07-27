from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID
import logging

from app.flow_v2.actions import RuntimeAction

FLOW_V2_EVENT_VERSION = 1
logger = logging.getLogger(__name__)


def resolve_runtime_choice_key(metadata: dict[str, Any] | None) -> str | None:
    """Return the canonical, provider-independent identifier for a Choice reply.

    IDs are deliberately preferred over labels. In particular, WhatsApp button
    titles are presentation text and must never replace ``button_reply.id``.
    """
    values = metadata or {}
    for field_name in ("selected_row_id", "interactive_reply_id", "row_id", "sourceHandle"):
        value = values.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


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


class AiRagAfterAnswerBehavior(StrEnum):
    END_FLOW = "end_flow"
    CONTINUE_TO_NEXT = "continue_to_next"
    WAIT_SAME_NODE = "wait_same_node"


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
        if self.message_text is not None and not metadata.get("message_text"):
            metadata["message_text"] = str(self.message_text)
        choice_id = resolve_runtime_choice_key(metadata)
        if choice_id:
            metadata.setdefault("runtime_choice_key", choice_id)
            metadata.setdefault("selected_row_id", choice_id)
            metadata.setdefault("row_id", choice_id)
            metadata.setdefault("sourceHandle", choice_id)
        logger.info(
            "event=meta_webhook_interactive_pipeline stage=runtime_input input_message_id=%s "
            "message.type=%s interactive.type=%s button_reply.id=%s interactive_reply_id=%s "
            "selected_row_id=%s row_id=%s runtime_choice_key=%s message_text=%s current_node_id=%s next_node_id=%s",
            self.input_message_id or "n/a",
            metadata.get("message_type") or "n/a",
            metadata.get("interactive_type") or "n/a",
            metadata.get("interactive_reply_id") or "n/a",
            metadata.get("interactive_reply_id") or "n/a",
            metadata.get("selected_row_id") or "n/a",
            metadata.get("row_id") or "n/a",
            metadata.get("runtime_choice_key") or "n/a",
            self.message_text or "n/a",
            metadata.get("current_node_id") or "n/a",
            metadata.get("next_node_id") or "n/a",
        )
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class RuntimeOutput:
    session_id: UUID
    status: FlowV2SessionStatus
    current_node_id: str | None
    effects: tuple[dict[str, Any], ...] = ()
    actions: tuple[RuntimeAction, ...] = ()
    emitted_event_count: int = 0
