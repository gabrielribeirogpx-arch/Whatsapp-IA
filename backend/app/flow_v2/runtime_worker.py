from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.flow_v2.actions import RuntimeAction, action_from_effect
from app.flow_v2.channel_adapter import ChannelAdapter
from app.flow_v2.contracts import RuntimeInput, RuntimeOutput
from app.flow_v2.executor import FlowV2Executor


@dataclass(frozen=True)
class FlowV2InputEvent:
    tenant_id: UUID
    flow_version_id: UUID
    external_user_id: str
    message_text: str | None = None
    contact_id: UUID | None = None
    conversation_id: UUID | None = None
    input_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_runtime_input(self) -> RuntimeInput:
        return RuntimeInput(
            tenant_id=self.tenant_id,
            flow_version_id=self.flow_version_id,
            external_user_id=self.external_user_id,
            message_text=self.message_text,
            contact_id=self.contact_id,
            conversation_id=self.conversation_id,
            input_message_id=self.input_message_id,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class FlowV2WorkerResult:
    runtime_output: RuntimeOutput
    actions: tuple[RuntimeAction, ...]
    deliveries: tuple[dict[str, Any], ...]


class FlowV2RuntimeWorker:
    """Operational Runtime V2 pipeline.

    Input Event -> FlowV2Executor -> Event Store -> Actions -> Channel Adapter.
    The worker never sends content directly; it delegates every outbound command
    to the configured channel adapter.
    """

    def __init__(self, *, executor: FlowV2Executor | None = None, channel_adapter: ChannelAdapter | None = None) -> None:
        self.executor = executor or FlowV2Executor()
        self.channel_adapter = channel_adapter

    def process(self, db: Session, input_event: FlowV2InputEvent | RuntimeInput) -> FlowV2WorkerResult:
        runtime_input = input_event if isinstance(input_event, RuntimeInput) else input_event.to_runtime_input()
        runtime_output = self.executor.handle_input(db, runtime_input)
        actions = runtime_output.actions or tuple(
            action
            for effect in runtime_output.effects
            if (action := action_from_effect(
                effect=effect,
                tenant_id=runtime_input.tenant_id,
                session_id=runtime_output.session_id,
                external_user_id=runtime_input.external_user_id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
            ))
            is not None
        )
        deliveries: list[dict[str, Any]] = []
        if self.channel_adapter is not None:
            deliveries = [self.channel_adapter.dispatch(action) for action in actions]
        return FlowV2WorkerResult(runtime_output=runtime_output, actions=tuple(actions), deliveries=tuple(deliveries))
