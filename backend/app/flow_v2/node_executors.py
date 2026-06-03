from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.flow_v2.contracts import FlowV2EventType, RuntimeInput
from app.flow_v2.models import FlowV2ScheduledJob
from app.flow_v2.snapshot import FlowV2Snapshot
from app.flow_v2.transition_resolver import TransitionResolver


@dataclass(frozen=True)
class NodeExecutionResult:
    effects: tuple[dict[str, Any], ...] = ()
    next_node_id: str | None = None
    status: str = "continue"


class NodeExecutor(Protocol):
    def execute(
        self,
        db,
        *,
        snapshot: FlowV2Snapshot,
        session: Any,
        node: dict[str, Any],
        runtime_input: RuntimeInput,
    ) -> NodeExecutionResult: ...


class BaseNodeExecutor:
    def __init__(self, *, event_store, transition_resolver: TransitionResolver) -> None:
        self.event_store = event_store
        self.transition_resolver = transition_resolver

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}

    def _default_next(self, db, *, snapshot: FlowV2Snapshot, session: Any, node_id: str) -> str:
        return self.transition_resolver.resolve(db, snapshot=snapshot, session=session, source_node_id=node_id).target_node_id


class MessageNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        message = node.get("content") or node.get("text") or data.get("content") or data.get("text") or data.get("message")
        message = "" if message is None else str(message)
        payload = {"node_id": node_id, "message": message}
        self.event_store.append(db, session=session, event_type=FlowV2EventType.MESSAGE_SENT, node_id=node_id, payload=payload)
        next_node_id = self._default_next(db, snapshot=snapshot, session=session, node_id=node_id)
        return NodeExecutionResult(effects=({"type": "send_message", "text": message},), next_node_id=next_node_id)


class ChoiceNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        options = node.get("options") or data.get("options") or []
        option_ids = [str(option["id"]) for option in options if isinstance(option, dict) and option.get("id") is not None]
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CHOICE_SHOWN,
            node_id=node_id,
            payload={"node_id": node_id, "option_ids": option_ids},
        )
        row_id = runtime_input.metadata.get("row_id") or runtime_input.metadata.get("sourceHandle")
        if row_id is None:
            return NodeExecutionResult(status="wait")
        row_id = str(row_id)
        if row_id not in option_ids:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=node_id,
                payload={"source_handle": row_id, "allowed_option_ids": option_ids},
            )
            raise RuntimeError("Runtime V2 choice option not found")
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CHOICE_SELECTED,
            node_id=node_id,
            payload={"node_id": node_id, "row_id": row_id},
        )
        next_node_id = self.transition_resolver.resolve(
            db, snapshot=snapshot, session=session, source_node_id=node_id, source_handle=row_id
        ).target_node_id
        return NodeExecutionResult(next_node_id=next_node_id)


class DelayNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        seconds = int(node.get("seconds") if node.get("seconds") is not None else data.get("seconds", 0))
        next_node_id = self._default_next(db, snapshot=snapshot, session=session, node_id=node_id)
        job = FlowV2ScheduledJob(
            id=uuid.uuid4(),
            tenant_id=session.tenant_id,
            session_id=session.id,
            resume_node_id=next_node_id,
            run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=seconds),
        )
        if hasattr(db, "add"):
            db.add(job)
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.DELAY_SCHEDULED,
            node_id=node_id,
            payload={"node_id": node_id, "seconds": seconds, "resume_node_id": next_node_id, "run_at": job.run_at.isoformat()},
        )
        return NodeExecutionResult(status="scheduled", next_node_id=next_node_id)


class ConditionNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        conditions = node.get("conditions") or data.get("conditions") or []
        result = all(self._evaluate(condition, runtime_input.metadata) for condition in conditions)
        handle = "true" if result else "false"
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CONDITION_EVALUATED,
            node_id=node_id,
            payload={"node_id": node_id, "result": result, "source_handle": handle},
        )
        next_node_id = self.transition_resolver.resolve(
            db, snapshot=snapshot, session=session, source_node_id=node_id, source_handle=handle
        ).target_node_id
        return NodeExecutionResult(next_node_id=next_node_id)

    @classmethod
    def _evaluate(cls, condition: Any, metadata: dict[str, Any]) -> bool:
        if not isinstance(condition, dict):
            return False
        left = condition.get("left") or condition.get("field") or condition.get("path")
        expected = condition.get("right") if "right" in condition else condition.get("value")
        operator = condition.get("operator") or condition.get("op") or "=="
        if operator not in {"==", "eq", "equals"} or not left:
            return False
        return cls._get_path(metadata, str(left)) == expected

    @staticmethod
    def _get_path(values: dict[str, Any], path: str) -> Any:
        current: Any = values
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current


class NodeExecutorRegistry:
    def __init__(self, *, event_store, transition_resolver: TransitionResolver) -> None:
        self._executors: dict[str, NodeExecutor] = {
            "message": MessageNodeExecutor(event_store=event_store, transition_resolver=transition_resolver),
            "choice": ChoiceNodeExecutor(event_store=event_store, transition_resolver=transition_resolver),
            "delay": DelayNodeExecutor(event_store=event_store, transition_resolver=transition_resolver),
            "condition": ConditionNodeExecutor(event_store=event_store, transition_resolver=transition_resolver),
        }

    def get(self, node_type: str) -> NodeExecutor:
        try:
            return self._executors[node_type]
        except KeyError as exc:
            raise RuntimeError(f"Unsupported Runtime V2 node type: {node_type}") from exc
