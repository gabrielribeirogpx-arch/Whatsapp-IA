from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.flow_v2.actions import RuntimeAction, action_from_effect
from app.flow_v2.channel_adapter import ChannelAdapter
from app.flow_v2.contracts import RuntimeInput, RuntimeOutput
from app.flow_v2.dead_letter import FlowV2DeadLetterQueue
from app.flow_v2.executor import FlowV2Executor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowV2InputEvent:
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
            event_id=self.event_id,
            message_id=self.message_id,
            webhook_id=self.webhook_id,
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

    def __init__(
        self,
        *,
        executor: FlowV2Executor | None = None,
        channel_adapter: ChannelAdapter | None = None,
        dead_letter_queue: FlowV2DeadLetterQueue | None = None,
    ) -> None:
        self.executor = executor or FlowV2Executor()
        self.channel_adapter = channel_adapter
        self.dead_letter_queue = dead_letter_queue or FlowV2DeadLetterQueue()

    def process(self, db: Session, input_event: FlowV2InputEvent | RuntimeInput) -> FlowV2WorkerResult:
        runtime_input = input_event if isinstance(input_event, RuntimeInput) else input_event.to_runtime_input()
        logger.info(
            "[V2 SNAPSHOT] worker_process tenant_id=%s flow_version_id=%s external_user_id=%s metadata_keys=%s",
            runtime_input.tenant_id,
            runtime_input.flow_version_id,
            runtime_input.external_user_id,
            sorted(runtime_input.metadata.keys()),
        )
        try:
            runtime_output = self.executor.handle_input(db, runtime_input)
        except Exception as exc:
            logger.exception(
                "[V2 SNAPSHOT] worker_failed tenant_id=%s flow_version_id=%s error_type=%s error=%s",
                runtime_input.tenant_id,
                runtime_input.flow_version_id,
                type(exc).__name__,
                exc,
            )
            self.dead_letter_queue.record(
                db,
                tenant_id=runtime_input.tenant_id,
                session_id=None,
                flow_version_id=runtime_input.flow_version_id,
                event={
                    "external_user_id": runtime_input.external_user_id,
                    "input_message_id": runtime_input.input_message_id,
                    "metadata": runtime_input.metadata,
                },
                error=exc,
            )
            raise
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
        if runtime_input.metadata.get("event_type") == "DELAY_RESUMED":
            logger.info(
                "[DELAY_RESUMED] worker_after_process session_id=%s status=%s current_node_id=%s runtime_output_actions_count=%s worker_actions_count=%s runtime_output_actions_empty=%s worker_actions_empty=%s",
                runtime_output.session_id,
                runtime_output.status,
                runtime_output.current_node_id,
                len(runtime_output.actions),
                len(actions),
                len(runtime_output.actions) == 0,
                len(actions) == 0,
            )
        deliveries: list[dict[str, Any]] = []
        if self.channel_adapter is not None:
            deliveries = [self.channel_adapter.dispatch(action) for action in actions]
        logger.info(
            "[V2 NODE EXECUTION] worker_done session_id=%s status=%s current_node_id=%s actions_count=%s deliveries_count=%s",
            runtime_output.session_id,
            runtime_output.status,
            runtime_output.current_node_id,
            len(actions),
            len(deliveries),
        )
        return FlowV2WorkerResult(runtime_output=runtime_output, actions=tuple(actions), deliveries=tuple(deliveries))
