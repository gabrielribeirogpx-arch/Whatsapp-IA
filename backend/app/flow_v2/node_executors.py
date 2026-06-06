from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.flow_v2.actions import (
    RuntimeAction,
    ScheduleDelayAction,
    SendChoiceButtonsAction,
    SendMessageAction,
)
from app.flow_v2.contracts import FlowV2EventType, RuntimeInput
from app.flow_v2.models import FlowV2ScheduledJob
from app.flow_v2.snapshot import FlowV2Snapshot, build_transitions_from_edges
from app.flow_v2.transition_resolver import TransitionResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeExecutionResult:
    actions: tuple[RuntimeAction, ...] = ()
    next_node_id: str | None = None
    status: str = "continue"

    @property
    def effects(self) -> tuple[dict[str, Any], ...]:
        return tuple(action.as_effect() for action in self.actions)


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

    def _default_next(
        self, db, *, snapshot: FlowV2Snapshot, session: Any, node_id: str
    ) -> str:
        logger.info(
            "[V2 NODE EXECUTION] resolving_default_next node_id=%s start_node_id=%s transitions_count=%s edges_count=%s",
            node_id,
            snapshot.start_node_id,
            len(snapshot.transitions),
            len(snapshot.edges),
        )
        return self.transition_resolver.resolve(
            db, snapshot=snapshot, session=session, source_node_id=node_id
        ).target_node_id

    def _default_next_or_terminal(
        self, db, *, snapshot: FlowV2Snapshot, session: Any, node_id: str
    ) -> str | None:
        transitions = (
            list(snapshot.transitions)
            if snapshot.transitions
            else build_transitions_from_edges(snapshot.edges)
        )
        outgoing = [
            transition
            for transition in transitions
            if str(transition.get("source_node_id")) == node_id
        ]
        if not outgoing:
            logger.info("[V2 NODE EXECUTION] terminal_node node_id=%s", node_id)
            return None
        return self._default_next(
            db, snapshot=snapshot, session=session, node_id=node_id
        )


class MessageNodeExecutor(BaseNodeExecutor):
    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        message = (
            node.get("content")
            or node.get("text")
            or data.get("content")
            or data.get("text")
            or data.get("message")
        )
        message = "" if message is None else str(message)
        is_start = bool(node.get("isStart") or data.get("isStart"))
        logger.info(
            "[MESSAGE EXECUTED] node_id=%s is_start=%s message_preview=%s",
            node_id,
            is_start,
            message[:120],
        )
        next_node_id = self._default_next_or_terminal(
            db, snapshot=snapshot, session=session, node_id=node_id
        )
        next_node = snapshot.node_by_id.get(next_node_id) if next_node_id else None
        next_node_data = self._node_data(next_node) if isinstance(next_node, dict) else {}
        next_node_type = (
            str(next_node.get("type") or next_node_data.get("type") or "message")
            if isinstance(next_node, dict)
            else None
        )
        logger.info(
            "[MESSAGE NEXT NODE] node_id=%s next_node_id=%s next_node_type=%s",
            node_id,
            next_node_id,
            next_node_type,
        )
        actions: tuple[RuntimeAction, ...] = ()
        if message:
            payload = {"node_id": node_id, "message": message}
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.MESSAGE_SENT,
                node_id=node_id,
                payload=payload,
            )
            action_metadata = {**runtime_input.metadata, "node_id": node_id}
            action = SendMessageAction(
                tenant_id=session.tenant_id,
                session_id=session.id,
                external_user_id=runtime_input.external_user_id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                text=message,
                metadata=action_metadata,
            )
            logger.info(
                "[V2 SEND ACTION] tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s node_id=%s metadata_keys=%s",
                action.tenant_id,
                action.metadata.get("provider_id"),
                action.session_id,
                action.conversation_id,
                action.contact_id,
                node_id,
                sorted(action.metadata.keys()),
            )
            actions = (action,)
        legacy_wait_after_start_condition = is_start and next_node_id is not None
        wait_after_start_condition = legacy_wait_after_start_condition and next_node_type != "choice"
        status = (
            "complete"
            if next_node_id is None
            else ("wait" if wait_after_start_condition else "continue")
        )
        logger.info(
            "[MESSAGE AUTO CONTINUE] node_id=%s next_node_id=%s next_node_type=%s status=%s auto_continue=%s legacy_wait_after_start_condition=%s wait_after_start_condition=%s blocking_condition=%s",
            node_id,
            next_node_id,
            next_node_type,
            status,
            status == "continue",
            legacy_wait_after_start_condition,
            wait_after_start_condition,
            "isStart && next_node_id && next_node_type != choice" if wait_after_start_condition else "none",
        )
        return NodeExecutionResult(
            actions=actions,
            next_node_id=next_node_id,
            status=status,
        )


def _choice_prompt(node: dict[str, Any], data: dict[str, Any]) -> str:
    prompt = (
        node.get("content")
        or node.get("text")
        or data.get("content")
        or data.get("text")
        or data.get("message")
        or data.get("body_text")
        or data.get("title")
    )
    return str(prompt or "Escolha uma opção")


def _choice_buttons_from_options(options: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(options, list):
        return ()

    buttons: list[dict[str, Any]] = []
    for option in options[:3]:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("id") or option.get("handleId") or option.get("handle_id") or "").strip()
        title = str(option.get("label") or option.get("title") or "").strip()
        if not option_id or not title:
            continue
        buttons.append({"id": option_id, "title": title[:20]})
    return tuple(buttons)


def _choice_options_payload(options: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(options, list):
        return ()
    payload: list[dict[str, Any]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("id") or "").strip()
        label = str(option.get("label") or "").strip()
        if option_id and label:
            payload.append({"id": option_id, "label": label})
    return tuple(payload)


class ChoiceNodeExecutor(BaseNodeExecutor):
    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        options = node.get("options") or data.get("options") or []
        option_ids = [
            str(option["id"])
            for option in options
            if isinstance(option, dict) and option.get("id") is not None
        ]
        choice_log_payload = {
            "node_id": node_id,
            "session_id": str(session.id),
            "options_count": len(options) if isinstance(options, list) else 0,
            "options": options if isinstance(options, list) else [],
            "provider_id": runtime_input.metadata.get("provider_id"),
            "tenant_id": str(session.tenant_id),
            "message_type": "wait_choice",
            "payload": {
                "row_id": runtime_input.metadata.get("row_id")
                or runtime_input.metadata.get("sourceHandle"),
                "current_node_id": getattr(session, "current_node_id", None),
                "session_status": getattr(session, "status", None),
            },
        }
        logger.info("[V2 CHOICE NODE] %s", json.dumps(choice_log_payload, default=str, ensure_ascii=False, sort_keys=True))
        logger.info("[V2 CHOICE OPTIONS] %s", json.dumps(choice_log_payload, default=str, ensure_ascii=False, sort_keys=True))
        logger.info(
            "[V2 NODE EXECUTION] choice node_id=%s option_ids=%s row_id=%s",
            node_id,
            option_ids,
            runtime_input.metadata.get("row_id")
            or runtime_input.metadata.get("sourceHandle"),
        )
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CHOICE_SHOWN,
            node_id=node_id,
            payload={"node_id": node_id, "option_ids": option_ids},
        )
        row_id = runtime_input.metadata.get("row_id") or runtime_input.metadata.get(
            "sourceHandle"
        )
        logger.info(
            "[CHOICE PARSED] source=RuntimeV2ChoiceResolver node_id=%s session_id=%s message_text=%s row_id=%s sourceHandle=%s selected_row_id=%s interactive_reply_id=%s expected_runtime_choice_key=row_id_or_sourceHandle option_ids=%s",
            node_id,
            session.id,
            runtime_input.message_text,
            runtime_input.metadata.get("row_id"),
            runtime_input.metadata.get("sourceHandle"),
            runtime_input.metadata.get("selected_row_id"),
            runtime_input.metadata.get("interactive_reply_id"),
            option_ids,
        )
        if row_id is None:
            buttons = _choice_buttons_from_options(options)
            action_metadata = {
                **runtime_input.metadata,
                "node_id": node_id,
                "node_type": "choice",
            }
            logger.info(
                "[V2 CHOICE EXECUTED]\nnode_id=%s\noptions=%s\nbuttons=%s",
                node_id,
                json.dumps(_choice_options_payload(options), default=str, ensure_ascii=False, sort_keys=True),
                json.dumps(buttons, default=str, ensure_ascii=False, sort_keys=True),
            )
            action = SendChoiceButtonsAction(
                tenant_id=session.tenant_id,
                session_id=session.id,
                external_user_id=runtime_input.external_user_id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                text=_choice_prompt(node, data),
                node_id=node_id,
                options=_choice_options_payload(options),
                buttons=buttons,
                metadata=action_metadata,
            )
            result = NodeExecutionResult(actions=(action,), status="wait")
            logger.error(
                "[CHOICE OPTION NOT FOUND] node_id=%s session_id=%s reason=missing_runtime_choice_key row_id=%s sourceHandle=%s selected_row_id=%s interactive_reply_id=%s message_text=%s expected_runtime_choice_key=row_id_or_sourceHandle",
                node_id,
                session.id,
                runtime_input.metadata.get("row_id"),
                runtime_input.metadata.get("sourceHandle"),
                runtime_input.metadata.get("selected_row_id"),
                runtime_input.metadata.get("interactive_reply_id"),
                runtime_input.message_text,
            )
            logger.info(
                "[CHOICE EXECUTION COMPLETE] node_id=%s session_id=%s status=%s next_node_id=%s actions_count=%s reason=waiting_for_choice_selection",
                node_id,
                session.id,
                result.status,
                result.next_node_id,
                len(result.actions),
            )
            logger.info(
                "[V2 CHOICE ACTION] %s",
                json.dumps(
                    {
                        **choice_log_payload,
                        "message_type": "interactive",
                        "payload": {
                            "status": result.status,
                            "next_node_id": result.next_node_id,
                            "actions": [runtime_action.as_effect() for runtime_action in result.actions],
                        },
                    },
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            return result
        row_id = str(row_id)
        if row_id not in option_ids:
            logger.error(
                "[CHOICE OPTION NOT FOUND] node_id=%s session_id=%s received_row_id=%s allowed_option_ids=%s selected_row_id=%s interactive_reply_id=%s reason=row_id_not_in_option_ids",
                node_id,
                session.id,
                row_id,
                option_ids,
                runtime_input.metadata.get("selected_row_id"),
                runtime_input.metadata.get("interactive_reply_id"),
            )
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=node_id,
                payload={"source_handle": row_id, "allowed_option_ids": option_ids},
            )
            raise RuntimeError("Runtime V2 choice option not found")
        logger.info(
            "[CHOICE OPTION MATCHED] node_id=%s session_id=%s received_row_id=%s allowed_option_ids=%s",
            node_id,
            session.id,
            row_id,
            option_ids,
        )
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CHOICE_SELECTED,
            node_id=node_id,
            payload={"node_id": node_id, "row_id": row_id},
        )
        next_node_id = self.transition_resolver.resolve(
            db,
            snapshot=snapshot,
            session=session,
            source_node_id=node_id,
            source_handle=row_id,
        ).target_node_id
        logger.info(
            "[CHOICE NEXT NODE] node_id=%s session_id=%s source_handle=%s next_node_id=%s next_node_exists=%s",
            node_id,
            session.id,
            row_id,
            next_node_id,
            next_node_id in snapshot.node_by_id,
        )
        result = NodeExecutionResult(next_node_id=next_node_id)
        logger.info(
            "[CHOICE EXECUTION COMPLETE] node_id=%s session_id=%s status=%s next_node_id=%s actions_count=%s",
            node_id,
            session.id,
            result.status,
            result.next_node_id,
            len(result.actions),
        )
        logger.info(
            "[V2 CHOICE ACTION] %s",
            json.dumps(
                {
                    **choice_log_payload,
                    "payload": {
                        "status": result.status,
                        "next_node_id": result.next_node_id,
                        "actions": [runtime_action.as_effect() for runtime_action in result.actions],
                    },
                },
                default=str,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return result


class DelayNodeExecutor(BaseNodeExecutor):
    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        seconds = int(
            node.get("seconds")
            if node.get("seconds") is not None
            else data.get("seconds", 0)
        )
        logger.info("[V2 NODE EXECUTION] delay node_id=%s seconds=%s", node_id, seconds)
        next_node_id = self._default_next(
            db, snapshot=snapshot, session=session, node_id=node_id
        )
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
            payload={
                "node_id": node_id,
                "seconds": seconds,
                "resume_node_id": next_node_id,
                "run_at": job.run_at.isoformat(),
            },
        )
        action = ScheduleDelayAction(
            tenant_id=session.tenant_id,
            session_id=session.id,
            external_user_id=runtime_input.external_user_id,
            conversation_id=runtime_input.conversation_id,
            contact_id=runtime_input.contact_id,
            job_id=job.id,
            resume_node_id=next_node_id,
            run_at=job.run_at,
            seconds=seconds,
        )
        return NodeExecutionResult(
            actions=(action,), status="scheduled", next_node_id=next_node_id
        )


class ConditionNodeExecutor(BaseNodeExecutor):
    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        conditions = node.get("conditions") or data.get("conditions") or []
        keywords = self._keywords_from_builder_data(data)
        match_type = (
            str(data.get("matchType") or data.get("match_type") or "equals")
            .strip()
            .lower()
        )
        message = (
            ""
            if runtime_input.message_text is None
            else str(runtime_input.message_text)
        )

        logger.info("[V2 CONDITION SNAPSHOT NODE] node_id=%s node=%s", node_id, node)
        logger.info("[V2 CONDITION NODE DATA] node_id=%s data=%s", node_id, data)

        if keywords:
            result = self._evaluate_builder_keywords(
                message=message, keywords=keywords, match_type=match_type
            )
        else:
            result = bool(conditions) and all(
                self._evaluate(condition, runtime_input.metadata)
                for condition in conditions
            )

        handle = "true" if result else "false"
        resolution = self.transition_resolver.resolve(
            db,
            snapshot=snapshot,
            session=session,
            source_node_id=node_id,
            source_handle=handle,
        )
        next_node_id = resolution.target_node_id
        logger.info(
            "[V2 CONDITION] node_id=%s message=%s keywords=%s match_type=%s result=%s source_handle=%s target_node_id=%s",
            node_id,
            message,
            keywords,
            match_type,
            result,
            handle,
            next_node_id,
        )
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.CONDITION_EVALUATED,
            node_id=node_id,
            payload={
                "node_id": node_id,
                "conditions": conditions,
                "message": message,
                "keywords": keywords,
                "match_type": match_type,
                "result": result,
                "source_handle": handle,
                "target_node_id": next_node_id,
            },
        )
        return NodeExecutionResult(next_node_id=next_node_id)

    @classmethod
    def _evaluate(cls, condition: Any, metadata: dict[str, Any]) -> bool:
        if not isinstance(condition, dict):
            return False
        left = condition.get("left") or condition.get("field") or condition.get("path")
        expected = (
            condition.get("right") if "right" in condition else condition.get("value")
        )
        operator = condition.get("operator") or condition.get("op") or "=="
        if operator not in {"==", "eq", "equals"} or not left:
            return False
        return cls._get_path(metadata, str(left)) == expected

    @classmethod
    def _evaluate_builder_keywords(
        cls, *, message: str, keywords: list[str], match_type: str
    ) -> bool:
        normalized_message = cls._normalize_text(message)
        normalized_keywords = [
            cls._normalize_text(keyword)
            for keyword in keywords
            if cls._normalize_text(keyword)
        ]
        if not normalized_keywords:
            return False
        if match_type == "contains":
            return any(keyword in normalized_message for keyword in normalized_keywords)
        return any(normalized_message == keyword for keyword in normalized_keywords)

    @staticmethod
    def _keywords_from_builder_data(data: dict[str, Any]) -> list[str]:
        for key in ("keywords", "positive", "condition"):
            raw_value = data.get(key)
            keywords = ConditionNodeExecutor._coerce_keywords(raw_value)
            if keywords:
                return keywords
        return []

    @staticmethod
    def _coerce_keywords(raw_value: Any) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str):
            return [
                part.strip()
                for part in raw_value.replace("\n", ",").split(",")
                if part.strip()
            ]
        return []

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().casefold()

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
            "message": MessageNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "choice": ChoiceNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "delay": DelayNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "condition": ConditionNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
        }

    def get(self, node_type: str) -> NodeExecutor:
        try:
            return self._executors[node_type]
        except KeyError as exc:
            raise RuntimeError(
                f"Unsupported Runtime V2 node type: {node_type}"
            ) from exc
