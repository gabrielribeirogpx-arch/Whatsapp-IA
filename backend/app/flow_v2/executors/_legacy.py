from __future__ import annotations

import json
import os
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import inspect as sqlalchemy_inspect, or_, select

from app.flow_v2.actions import (
    RuntimeAction,
    ScheduleDelayAction,
    SendChoiceButtonsAction,
    SendCtaUrlAction,
    SendMediaAction,
    SendMessageAction,
)
from app.flow_v2.contracts import AiRagAfterAnswerBehavior, FlowV2EventType, RuntimeInput
from app.flow_v2.models import FlowV2ScheduledJob
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_log import ConversationLog
from app.models.flow import FlowVersion
from app.models.lead import Lead
from app.models.task import Task
from app.services.contact_tag_service import add_tag_to_contact
from app.services.conversation_mode_service import ConversationModeError, set_conversation_mode
from app.services.audit_service import write_audit_log
from app.services.realtime_service import sync_publish
from app.services.flow_ai_memory_service import flow_ai_memory_service
from app.services.contextual_query_service import (
    contains_context_reference,
    generate_standalone_question,
    get_cached_standalone,
    is_greeting,
    store_cached_standalone,
)
from app.services.rag_service import answer_with_rag
from app.services.llm_service import generate_answer_for_tenant
from app.services.ai_structured_service import classify_for_tenant, extract_for_tenant
from app.services.ai_summary_service import summarize_for_tenant
from app.services.ai_agent_service import run_agent_for_tenant
from app.services.ai_system_pending_event import message_has_date_or_time, pending_event_lookup
from app.services.supervisor_service import FALLBACK_MESSAGE as SUPERVISOR_FALLBACK_MESSAGE, MAX_SUPERVISOR_DEPTH, build_available_agents, decide_supervisor_agent, get_supervisor_context
from app.services.context_builder_service import build_context, context_builder_enabled
from app.services.long_term_memory_service import store_fact
from app.services.ai_execution_service import get_flow_id, record_ai_execution, redact_text, resolve_ai_config, score_confidence
from app.services.execution_budget_service import ExecutionBudgetExceeded, get_or_create_budget, persist_budget
from app.flow_v2.snapshot import FlowV2Snapshot, build_transitions_from_edges
from app.flow_v2.transition_resolver import TransitionResolver
from app.flow_v2.template_renderer import FlowRenderContext, render_template

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeExecutionResult:
    actions: tuple[RuntimeAction, ...] = ()
    next_node_id: str | None = None
    status: str = "continue"
    next_source_handle: str | None = None
    intent: str | None = None

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


    @staticmethod
    def _render_context(db, *, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput) -> FlowRenderContext:
        contact = ActionNodeExecutor._resolve_contact(db, runtime_input=runtime_input)
        conversation = ActionNodeExecutor._resolve_conversation(db, runtime_input=runtime_input)
        lead = ActionNodeExecutor._resolve_lead(
            db,
            runtime_input=runtime_input,
            contact_id=runtime_input.contact_id or getattr(conversation, "contact_id", None),
            conversation_id=runtime_input.conversation_id or getattr(conversation, "id", None),
        )
        return FlowRenderContext(
            tenant_id=session.tenant_id,
            external_user_id=runtime_input.external_user_id,
            phone=ActionNodeExecutor._phone_from_runtime_input(runtime_input),
            contact=contact,
            conversation=conversation,
            lead=lead,
            last_message=runtime_input.message_text,
            flow={"id": getattr(snapshot, "flow_id", None), "name": getattr(snapshot, "name", None)},
            session=session,
        )

    def _render(self, value: Any, db, *, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput) -> Any:
        return render_template(value, self._render_context(db, snapshot=snapshot, session=session, runtime_input=runtime_input))

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


def extract_message_text_from_node(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    data = BaseNodeExecutor._node_data(node)
    message = (
        node.get("content")
        or node.get("text")
        or data.get("content")
        or data.get("text")
        or data.get("message")
    )
    return "" if message is None else str(message)


def calculate_typing_delay_seconds(text: str) -> float:
    normalized_text = re.sub(r"\s+", " ", str(text or "").strip())
    return min(max(len(normalized_text) / 18, 1.2), 5.0)


def _is_truthy_node_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
    return False


class MessageNodeExecutor(BaseNodeExecutor):
    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        message = self._render(extract_message_text_from_node(node), db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        is_start = bool(node.get("isStart") or data.get("isStart"))
        logger.info(
            "[MESSAGE EXECUTED] node_id=%s is_start=%s message_preview=%s",
            node_id,
            is_start,
            message[:120],
        )
        logger.info(
            "[MESSAGE NODE EXECUTION] node_id=%s is_start=%s message_present=%s message_preview=%s event_type=%s target_final_node=%s",
            node_id,
            is_start,
            bool(message),
            message[:120],
            runtime_input.metadata.get("event_type"),
            node_id == "bccab03d-830a-4dc1-9e67-bcadf5666eee",
        )
        next_node_id = self._default_next_or_terminal(
            db, snapshot=snapshot, session=session, node_id=node_id
        )
        next_node = snapshot.node_by_id.get(next_node_id) if next_node_id else None
        next_node_data = self._node_data(next_node) if isinstance(next_node, dict) else {}
        next_node_type = (
            str(next_node.get("type") or next_node_data.get("type") or "message")
            .strip()
            .lower()
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
            logger.info(
                "[SEND ACTION CREATED] tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s node_id=%s text_preview=%s metadata_keys=%s event_type=%s",
                action.tenant_id,
                action.metadata.get("provider_id"),
                action.session_id,
                action.conversation_id,
                action.contact_id,
                node_id,
                action.text[:120],
                sorted(action.metadata.keys()),
                runtime_input.metadata.get("event_type"),
            )
            actions = (action,)
        legacy_wait_after_start_condition = is_start and next_node_id is not None
        interactive_next_node_types = {"choice", "buttons", "buttons_node", "list", "list_node"}
        next_node_is_interactive = next_node_type in interactive_next_node_types
        # A message immediately followed by a condition is a conversational
        # boundary: the condition must evaluate the next inbound user message,
        # not the message that triggered the current runtime call.
        wait_after_start_condition = next_node_type == "condition"
        user_input_next_node_types = {"condition"}
        wait_after_user_input_next_node = next_node_type in user_input_next_node_types
        if wait_after_user_input_next_node and next_node_id is not None:
            logger.info(
                "event=message_node_waiting_for_reply message_node_id=%s next_node_id=%s",
                node_id,
                next_node_id,
            )
        wait_for_reply = _is_truthy_node_flag(
            node.get("wait_for_reply")
            if "wait_for_reply" in node
            else data.get("wait_for_reply", data.get("waitForReply", data.get("await_reply", data.get("awaitReply"))))
        )
        status = (
            "complete"
            if next_node_id is None
            else ("wait" if wait_for_reply or wait_after_user_input_next_node else "continue")
        )
        logger.info(
            "[MESSAGE AUTO CONTINUE] node_id=%s next_node_id=%s next_node_type=%s status=%s auto_continue=%s legacy_wait_after_start_condition=%s wait_after_start_condition=%s wait_after_user_input_next_node=%s wait_for_reply=%s next_node_is_interactive=%s blocking_condition=%s",
            node_id,
            next_node_id,
            next_node_type,
            status,
            status == "continue",
            legacy_wait_after_start_condition,
            wait_after_start_condition,
            wait_after_user_input_next_node,
            wait_for_reply,
            next_node_is_interactive,
            "none",
        )
        return NodeExecutionResult(
            actions=actions,
            next_node_id=next_node_id,
            status=status,
        )


class MediaNodeExecutor(BaseNodeExecutor):
    SUPPORTED_MEDIA_TYPES = {"image", "document", "audio", "video"}

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        media_type = str(node.get("media_type") or data.get("media_type") or "").strip().lower()
        media_url = str(self._render(node.get("media_url") or data.get("media_url") or data.get("url") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip()
        caption = str(self._render(node.get("caption") or data.get("caption") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip() or None
        if media_type == "audio":
            caption = None
        filename = str(self._render(node.get("filename") or data.get("filename") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip() or None
        if media_type not in self.SUPPORTED_MEDIA_TYPES:
            logger.error("[MEDIA NODE INVALID] node_id=%s reason=invalid_media_type media_type=%s", node_id, media_type or "missing")
            raise RuntimeError(f"Invalid media_type for media node {node_id}")
        if not media_url or not media_url.startswith("https://"):
            logger.error("[MEDIA NODE INVALID] node_id=%s reason=invalid_media_url media_type=%s media_url_present=%s", node_id, media_type, bool(media_url))
            raise RuntimeError(f"Invalid media_url for media node {node_id}")
        next_node_id = self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.MESSAGE_SENT, node_id=node_id, payload={"node_id": node_id, "media_type": media_type, "media_url": media_url, "caption": caption, "filename": filename})
        action = SendMediaAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, media_type=media_type, media_url=media_url, caption=caption, filename=filename if media_type == "document" else None, metadata={**runtime_input.metadata, "node_id": node_id, "node_type": "media"})
        logger.info(
            "[MEDIA NODE EXECUTED] flow_id=%s snapshot_id=%s node_id=%s media_type=%s media_url=%s caption_present=%s filename=%s next_node_id=%s",
            getattr(session, "flow_id", None),
            getattr(session, "flow_version_id", None),
            node_id,
            media_type,
            media_url,
            bool(caption),
            filename,
            next_node_id,
        )
        return NodeExecutionResult(actions=(action,), next_node_id=next_node_id, status="complete" if next_node_id is None else "continue")


class CtaUrlNodeExecutor(BaseNodeExecutor):
    MAX_BUTTON_TEXT_LENGTH = 20

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        text = str(self._render(node.get("text") or node.get("content") or data.get("text") or data.get("content") or data.get("message") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip()
        button_text = str(self._render(node.get("button_text") or data.get("button_text") or data.get("buttonText") or data.get("button") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip()
        url = str(self._render(node.get("url") or data.get("url") or data.get("href") or "", db, snapshot=snapshot, session=session, runtime_input=runtime_input)).strip()
        if not text:
            raise RuntimeError(f"CTA URL node {node_id} requires text")
        if not button_text:
            raise RuntimeError(f"CTA URL node {node_id} requires button_text")
        if len(button_text) > self.MAX_BUTTON_TEXT_LENGTH:
            raise RuntimeError(f"CTA URL node {node_id} button_text exceeds WhatsApp limit")
        if not url.startswith("https://"):
            raise RuntimeError(f"CTA URL node {node_id} requires https url")
        next_node_id = self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.MESSAGE_SENT, node_id=node_id, payload={"node_id": node_id, "message_type": "interactive", "interactive_type": "cta_url", "text": text, "button_text": button_text, "url": url})
        action = SendCtaUrlAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, button_text=button_text, url=url, metadata={**runtime_input.metadata, "node_id": node_id, "node_type": "cta_url"})
        logger.info("[CTA URL NODE EXECUTED] node_id=%s button_text=%s url=%s next_node_id=%s", node_id, button_text, url, next_node_id)
        return NodeExecutionResult(actions=(action,), next_node_id=next_node_id, status="complete" if next_node_id is None else "continue")


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


def _choice_sections_from_options(options: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(options, list):
        return ()

    rows: list[dict[str, Any]] = []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        row_id = str(option.get("id") or option.get("handleId") or option.get("handle_id") or f"option_{index + 1}").strip()
        title = str(option.get("label") or option.get("title") or f"Opção {index + 1}").strip()
        description = str(option.get("description") or "").strip()
        if not row_id or not title:
            continue
        row: dict[str, Any] = {"id": row_id, "title": title[:24]}
        if description:
            row["description"] = description[:72]
        rows.append(row)
    return ({"title": "Opções", "rows": rows},) if rows else ()


def _choice_display_mode(node: dict[str, Any], data: dict[str, Any]) -> str:
    raw = node.get("display_mode") or data.get("display_mode") or data.get("displayMode") or "buttons"
    mode = str(raw).strip().lower()
    return "list" if mode == "list" else "buttons"


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
        display_mode = _choice_display_mode(node, data)
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
            sections = _choice_sections_from_options(options)
            action_metadata = {
                **runtime_input.metadata,
                "node_id": node_id,
                "node_type": "choice",
                "display_mode": display_mode,
                "interactive_type": "list" if display_mode == "list" else "button",
            }
            logger.info(
                "[V2 CHOICE EXECUTED]\nnode_id=%s\ndisplay_mode=%s\noptions=%s\nbuttons=%s",
                node_id,
                display_mode,
                json.dumps(_choice_options_payload(options), default=str, ensure_ascii=False, sort_keys=True),
                json.dumps(buttons if display_mode == "buttons" else sections, default=str, ensure_ascii=False, sort_keys=True),
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
                sections=sections,
                display_mode=display_mode,
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "sim", "on"}
    return False


def _runtime_input_message_id(runtime_input: RuntimeInput) -> str | None:
    metadata = runtime_input.metadata or {}
    for value in (
        runtime_input.message_id,
        runtime_input.input_message_id,
        metadata.get("message_id"),
        metadata.get("wamid"),
        metadata.get("whatsapp_message_id"),
        metadata.get("incoming_message_id"),
        metadata.get("input_message_id"),
    ):
        if value:
            return str(value)
    return None


class DelayNodeExecutor(BaseNodeExecutor):
    @staticmethod
    def _node_type(node: dict[str, Any] | None) -> str | None:
        if not isinstance(node, dict):
            return None
        data = BaseNodeExecutor._node_data(node)
        return str(node.get("type") or data.get("type") or "message").strip().lower()

    @classmethod
    def _resolve_effective_seconds(
        cls,
        *,
        snapshot: FlowV2Snapshot,
        next_node_id: str | None,
        fallback_seconds: int | float,
        show_typing: bool,
        typing_duration_mode: str,
        session: Any,
        node_id: str,
    ) -> int | float:
        if not show_typing or typing_duration_mode != "auto":
            return fallback_seconds
        try:
            next_node = snapshot.node_by_id.get(next_node_id) if next_node_id else None
            next_node_type = cls._node_type(next_node)
            if next_node_type != "message":
                logger.info(
                    "[DELAY AUTO TYPING FALLBACK] session_id=%s node_id=%s next_node_id=%s next_node_type=%s reason=non_message",
                    session.id,
                    node_id,
                    next_node_id,
                    next_node_type,
                )
                return fallback_seconds
            return calculate_typing_delay_seconds(extract_message_text_from_node(next_node))
        except Exception:
            logger.warning(
                "[DELAY AUTO TYPING FALLBACK] session_id=%s node_id=%s next_node_id=%s reason=calculation_failed",
                session.id,
                node_id,
                next_node_id,
                exc_info=True,
            )
            return fallback_seconds

    @staticmethod
    def _send_typing_indicator(db, *, session: Any, node_id: str, runtime_input: RuntimeInput) -> None:
        try:
            from app.services.whatsapp_message_service import send_whatsapp_typing_indicator_safe

            metadata = dict(runtime_input.metadata or {})
            send_whatsapp_typing_indicator_safe(
                db,
                tenant_id=session.tenant_id,
                conversation_id=runtime_input.conversation_id,
                recipient_id=runtime_input.external_user_id,
                message_id=_runtime_input_message_id(runtime_input),
                context={
                    **metadata,
                    "flow_version_id": str(session.flow_version_id),
                    "session_id": str(session.id),
                    "node_id": node_id,
                    "node_type": "delay",
                    "flow_executor": "flow_v2:delay",
                },
            )
        except Exception:
            logger.warning(
                "[DELAY TYPING FAILED] session_id=%s node_id=%s reason=unexpected_exception",
                session.id,
                node_id,
                exc_info=True,
            )

    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        raw_seconds = node.get("seconds", data.get("seconds", 0))
        seconds = int(raw_seconds or 0)
        logger.info(
            "[DELAY EXECUTE INPUT] session_id=%s node_id=%s current_node_id=%s raw_seconds=%s seconds=%s node=%s",
            session.id,
            node_id,
            session.current_node_id,
            raw_seconds,
            seconds,
            node,
        )
        show_typing = _coerce_bool(data.get("show_typing", node.get("show_typing", False)))
        raw_typing_duration_mode = data.get("typing_duration_mode", node.get("typing_duration_mode", "delay"))
        typing_duration_mode = str(raw_typing_duration_mode or "delay").strip().lower()
        if typing_duration_mode not in {"delay", "auto"}:
            typing_duration_mode = "delay"
        next_node_id = self._default_next(
            db, snapshot=snapshot, session=session, node_id=node_id
        )
        effective_seconds = self._resolve_effective_seconds(
            snapshot=snapshot,
            next_node_id=next_node_id,
            fallback_seconds=seconds,
            show_typing=show_typing,
            typing_duration_mode=typing_duration_mode,
            session=session,
            node_id=node_id,
        )
        logger.info(
            "[DELAY EXECUTE NEXT] session_id=%s node_id=%s seconds=%s effective_seconds=%s show_typing=%s typing_duration_mode=%s next_node_id=%s",
            session.id,
            node_id,
            seconds,
            effective_seconds,
            show_typing,
            typing_duration_mode,
            next_node_id,
        )
        if show_typing:
            self._send_typing_indicator(db, session=session, node_id=node_id, runtime_input=runtime_input)
        job = FlowV2ScheduledJob(
            id=uuid.uuid4(),
            tenant_id=session.tenant_id,
            session_id=session.id,
            resume_node_id=next_node_id,
            run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=effective_seconds),
        )
        if hasattr(db, "add"):
            db.add(job)
        logger.info(
            "[DELAY JOB CREATED] session_id=%s job_id=%s resume_node_id=%s run_at=%s backend=flow_v2_scheduled_jobs",
            session.id,
            job.id,
            job.resume_node_id,
            job.run_at,
        )
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.DELAY_SCHEDULED,
            node_id=node_id,
            payload={
                "node_id": node_id,
                "seconds": effective_seconds,
                "configured_seconds": seconds,
                "typing_duration_mode": typing_duration_mode,
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
            seconds=effective_seconds,
        )
        result = NodeExecutionResult(
            actions=(action,), status="scheduled", next_node_id=next_node_id
        )
        logger.info(
            "[DELAY EXECUTE RETURN] session_id=%s node_id=%s status=%s next_node_id=%s actions_count=%s",
            session.id,
            node_id,
            result.status,
            result.next_node_id,
            len(result.actions),
        )
        return result


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


class ActionNodeExecutor(BaseNodeExecutor):
    SUPPORTED_ACTION_TYPES = {
        "create_lead",
        "add_tag",
        "notify_team",
        "transfer_human",
        "set_conversation_mode",
        "create_task",
    }

    def execute(
        self, db, *, snapshot, session, node, runtime_input
    ) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        action_type = self._action_type(node, data)
        params = self._action_params(node, data)

        if action_type not in self.SUPPORTED_ACTION_TYPES:
            logger.warning(
                "[ACTION NODE SKIPPED] node_id=%s action_type=%s reason=unsupported",
                node_id,
                action_type or "missing",
            )
        else:
            params = self._render_action_params(params, db, snapshot=snapshot, session=session, runtime_input=runtime_input, action_type=action_type)
            self._execute_action(
                db,
                session=session,
                node_id=node_id,
                action_type=action_type,
                params=params,
                runtime_input=runtime_input,
            )

        next_node_id = self._default_next_or_terminal(
            db, snapshot=snapshot, session=session, node_id=node_id
        )
        if next_node_id is None:
            return NodeExecutionResult(status="complete")
        return NodeExecutionResult(next_node_id=next_node_id, status="continue")

    @staticmethod
    def _action_type(node: dict[str, Any], data: dict[str, Any]) -> str:
        return str(
            node.get("action_type")
            or data.get("action_type")
            or data.get("actionType")
            or data.get("action")
            or ""
        ).strip().lower()

    @staticmethod
    def _action_params(node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        raw_params = data.get("params") or data.get("parameters") or node.get("params") or node.get("parameters")
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        for key in (
            "tag",
            "message",
            "reason",
            "lead_name",
            "mode",
            "notification_title",
            "notification_message",
            "notification_priority",
            "task_title",
            "task_description",
            "task_priority",
            "task_assignee",
            "task_due_minutes",
        ):
            if key in data and key not in params:
                params[key] = data[key]
        return params

    def _render_action_params(
        self,
        params: dict[str, Any],
        db,
        *,
        snapshot: FlowV2Snapshot,
        session: Any,
        runtime_input: RuntimeInput,
        action_type: str,
    ) -> dict[str, Any]:
        keys_by_action = {
            "notify_team": {"notification_title", "notification_message", "title", "message"},
            "create_task": {"task_title", "task_description", "task_assignee", "title", "description", "assigned_to"},
            "transfer_human": {"reason"},
        }
        keys = keys_by_action.get(action_type, set())
        if not keys:
            return params
        return {
            key: self._render(value, db, snapshot=snapshot, session=session, runtime_input=runtime_input) if key in keys else value
            for key, value in params.items()
        }

    def _execute_action(
        self,
        db,
        *,
        session: Any,
        node_id: str,
        action_type: str,
        params: dict[str, Any],
        runtime_input: RuntimeInput,
    ) -> None:
        try:
            if action_type == "create_lead":
                self._create_lead(db, session=session, runtime_input=runtime_input, params=params)
            elif action_type == "add_tag":
                self._add_tag(db, session=session, runtime_input=runtime_input, params=params)
            elif action_type == "notify_team":
                self._notify_team(db, session=session, node_id=node_id, runtime_input=runtime_input, params=params)
            elif action_type == "transfer_human":
                self._transfer_human(db, session=session, runtime_input=runtime_input, params=params)
            elif action_type == "set_conversation_mode":
                self._set_conversation_mode(db, session=session, runtime_input=runtime_input, params=params)
            elif action_type == "create_task":
                self._create_task(db, session=session, node_id=node_id, runtime_input=runtime_input, params=params)
        except ConversationModeError as exc:
            logger.warning(
                "[ACTION NODE FAILED CONTROLLED] node_id=%s action_type=%s error=%s",
                node_id,
                action_type,
                exc,
            )
            raise RuntimeError(str(exc)) from exc
        except Exception:
            logger.exception(
                "[ACTION NODE FAILED] node_id=%s action_type=%s",
                node_id,
                action_type,
            )
            return

        logger.info(
            "[ACTION NODE EXECUTED] node_id=%s action_type=%s params_keys=%s",
            node_id,
            action_type,
            sorted(params.keys()),
        )

    @staticmethod
    def _create_lead(db, *, session: Any, runtime_input: RuntimeInput, params: dict[str, Any]) -> None:
        from app.services.lead_auto_service import create_or_update_lead_from_flow_action

        phone = ActionNodeExecutor._phone_from_runtime_input(runtime_input)
        if not phone:
            return
        name = str(params.get("lead_name") or "").strip() or None
        create_or_update_lead_from_flow_action(
            db,
            tenant_id=session.tenant_id,
            phone=phone,
            contact_id=runtime_input.contact_id,
            conversation_id=runtime_input.conversation_id,
            lead_name=name,
            last_message=runtime_input.message_text,
            metadata=runtime_input.metadata,
        )

    @staticmethod
    def _add_tag(db, *, session: Any, runtime_input: RuntimeInput, params: dict[str, Any]) -> None:
        tag = str(params.get("tag") or params.get("label") or "").strip()
        if not tag:
            return
        contact = ActionNodeExecutor._resolve_contact(db, runtime_input=runtime_input)
        if contact is None:
            return
        conversation = ActionNodeExecutor._resolve_conversation(db, runtime_input=runtime_input)
        add_tag_to_contact(
            db,
            tenant_id=session.tenant_id,
            contact=contact,
            tag=tag,
            description=f"Tag '{tag}' adicionada automaticamente pelo Flow Builder.",
            metadata={"source": "flow_builder", "tag": tag},
            conversation=conversation,
        )

    @staticmethod
    def _notify_team(db, *, session: Any, node_id: str, runtime_input: RuntimeInput, params: dict[str, Any]) -> None:
        conversation = ActionNodeExecutor._resolve_conversation(db, runtime_input=runtime_input)
        if conversation is None:
            logger.info(
                "[ACTION NOTIFY TEAM SKIPPED] tenant_id=%s session_id=%s node_id=%s conversation_id=%s reason=conversation_not_found_or_tenant_mismatch",
                session.tenant_id,
                session.id,
                node_id,
                runtime_input.conversation_id,
            )
            return

        title = str(params.get("notification_title") or params.get("title") or "").strip()
        message = str(
            params.get("notification_message")
            or params.get("message")
            or "Novo atendimento requer atenção"
        ).strip()
        priority = ActionNodeExecutor._notification_priority(params.get("notification_priority") or params.get("priority"))
        display_text = " — ".join(part for part in (title, message) if part) or "Equipe notificada"
        metadata = {
            "tenant_id": str(session.tenant_id),
            "conversation_id": str(conversation.id),
            "title": title or None,
            "message": message,
            "priority": priority,
            "flow_execution_id": str(getattr(session, "id", "") or "") or None,
            "node_id": node_id,
        }

        write_audit_log(
            db,
            action="TEAM_NOTIFICATION_CREATED",
            tenant_id=session.tenant_id,
            entity_type="conversation",
            entity_id=conversation.id,
            metadata=metadata,
        )

        activity = ConversationLog(
            tenant_id=session.tenant_id,
            conversation_id=conversation.id,
            message=display_text,
            mode="human",
            intent="team_notification",
            flow_step=node_id,
            used_fallback=False,
            response="Equipe notificada",
            created_at=datetime.utcnow(),
        )
        if hasattr(db, "add"):
            db.add(activity)

        conversation.updated_at = datetime.utcnow()
        if hasattr(db, "add"):
            db.add(conversation)

        payload = {
            "event": "team_notification",
            "type": "team_notification",
            "refresh": ["activity", "conversations", "conversation"],
            "tenant_id": str(session.tenant_id),
            "conversation_id": str(conversation.id),
            "phone": getattr(conversation, "phone_number", None),
            "title": title,
            "message": message,
            "priority": priority,
            "activity": {
                "id": str(getattr(activity, "id", "") or uuid.uuid4()),
                "type": "TEAM_NOTIFICATION_CREATED",
                "title": title or "Equipe notificada",
                "description": message,
                "entity_type": "conversation",
                "entity_id": str(conversation.id),
                "contact_name": getattr(conversation, "name", None),
                "phone": getattr(conversation, "phone_number", None),
                "created_at": activity.created_at.isoformat(),
            },
        }
        sync_publish(f"dashboard:{session.tenant_id}", payload)
        sync_publish(f"{session.tenant_id}:{conversation.id}", payload)
        phone_number = getattr(conversation, "phone_number", None)
        if phone_number:
            sync_publish(f"{session.tenant_id}:{phone_number}", payload)

        logger.info(
            "[ACTION NOTIFY TEAM] tenant_id=%s session_id=%s node_id=%s conversation_id=%s priority=%s title=%s message=%s",
            session.tenant_id,
            session.id,
            node_id,
            conversation.id,
            priority,
            title,
            message[:200],
        )


    @staticmethod
    def _create_task(db, *, session: Any, node_id: str, runtime_input: RuntimeInput, params: dict[str, Any]) -> None:
        conversation = ActionNodeExecutor._resolve_conversation(db, runtime_input=runtime_input)
        if conversation is None:
            logger.info(
                "[ACTION CREATE TASK SKIPPED] tenant_id=%s session_id=%s node_id=%s conversation_id=%s reason=conversation_not_found_or_tenant_mismatch",
                session.tenant_id,
                session.id,
                node_id,
                runtime_input.conversation_id,
            )
            return

        now = datetime.utcnow()
        title = str(params.get("task_title") or params.get("title") or "Nova tarefa").strip() or "Nova tarefa"
        description = str(params.get("task_description") or params.get("description") or "").strip() or None
        priority = ActionNodeExecutor._task_priority(params.get("task_priority") or params.get("priority"))
        assigned_to = str(params.get("task_assignee") or params.get("assigned_to") or "").strip() or None
        due_minutes = ActionNodeExecutor._task_due_minutes(params.get("task_due_minutes") or params.get("due_minutes"))
        due_at = now + timedelta(minutes=due_minutes) if due_minutes > 0 else None
        contact_id = runtime_input.contact_id or getattr(conversation, "contact_id", None)
        lead = ActionNodeExecutor._resolve_lead(db, runtime_input=runtime_input, contact_id=contact_id, conversation_id=conversation.id)

        task = Task(
            id=uuid.uuid4(),
            tenant_id=session.tenant_id,
            conversation_id=conversation.id,
            contact_id=contact_id,
            lead_id=getattr(lead, "id", None),
            title=title,
            description=description,
            priority=priority,
            status="open",
            assigned_to=assigned_to,
            due_at=due_at,
            created_at=now,
            updated_at=now,
        )
        if hasattr(db, "add"):
            db.add(task)
            if hasattr(db, "flush"):
                db.flush()

        metadata = {
            "tenant_id": str(session.tenant_id),
            "task_id": str(task.id),
            "conversation_id": str(conversation.id),
            "contact_id": str(contact_id) if contact_id else None,
            "lead_id": str(task.lead_id) if task.lead_id else None,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "open",
            "assigned_to": assigned_to,
            "due_at": due_at.isoformat() if due_at else None,
            "due_minutes": due_minutes,
            "flow_execution_id": str(getattr(session, "id", "") or "") or None,
            "node_id": node_id,
        }
        write_audit_log(
            db,
            action="TASK_CREATED",
            tenant_id=session.tenant_id,
            entity_type="task",
            entity_id=task.id,
            metadata=metadata,
        )

        due_label = f"{due_minutes} min" if due_minutes > 0 else "sem prazo"
        log_message = " · ".join(
            part
            for part in (
                f"Título: {title}",
                f"Prioridade: {priority}",
                f"Responsável: {assigned_to}" if assigned_to else "Responsável: -",
                f"Prazo: {due_label}",
            )
            if part
        )
        activity = ConversationLog(
            tenant_id=session.tenant_id,
            conversation_id=conversation.id,
            message=log_message,
            mode="human",
            intent="task_created",
            flow_step=node_id,
            used_fallback=False,
            response="Tarefa criada",
            created_at=now,
        )
        if hasattr(db, "add"):
            db.add(activity)

        conversation.updated_at = now
        if hasattr(db, "add"):
            db.add(conversation)

        payload = {
            "event": "task_created",
            "type": "task_created",
            "action": "TASK_CREATED",
            "refresh": ["activity", "conversations", "conversation", "tasks"],
            "tenant_id": str(session.tenant_id),
            "conversation_id": str(conversation.id),
            "contact_id": str(contact_id) if contact_id else None,
            "lead_id": str(task.lead_id) if task.lead_id else None,
            "phone": getattr(conversation, "phone_number", None),
            "task": {
                "id": str(task.id),
                "title": title,
                "description": description,
                "priority": priority,
                "status": "open",
                "assigned_to": assigned_to,
                "due_at": due_at.isoformat() if due_at else None,
                "due_minutes": due_minutes,
            },
            "activity": {
                "id": str(getattr(activity, "id", "") or uuid.uuid4()),
                "type": "TASK_CREATED",
                "title": "📝 Tarefa criada",
                "description": log_message,
                "entity_type": "task",
                "entity_id": str(task.id),
                "contact_name": getattr(conversation, "name", None),
                "phone": getattr(conversation, "phone_number", None),
                "created_at": activity.created_at.isoformat(),
            },
        }
        sync_publish(f"dashboard:{session.tenant_id}", payload)
        sync_publish(f"{session.tenant_id}:{conversation.id}", payload)
        phone_number = getattr(conversation, "phone_number", None)
        if phone_number:
            sync_publish(f"{session.tenant_id}:{phone_number}", payload)

        logger.info(
            "[ACTION CREATE TASK] tenant_id=%s session_id=%s node_id=%s conversation_id=%s task_id=%s priority=%s due_minutes=%s",
            session.tenant_id,
            session.id,
            node_id,
            conversation.id,
            task.id,
            priority,
            due_minutes,
        )

    @staticmethod
    def _task_priority(value: Any) -> str:
        normalized = str(value or "normal").strip().lower()
        aliases = {"low": "low", "baixa": "low", "normal": "normal", "high": "high", "alta": "high"}
        return aliases.get(normalized, "normal")

    @staticmethod
    def _task_due_minutes(value: Any) -> int:
        if value in (None, ""):
            return 60
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return 60
        return max(parsed, 0)

    @staticmethod
    def _resolve_lead(db, *, runtime_input: RuntimeInput, contact_id: Any = None, conversation_id: Any = None):
        if not hasattr(db, "execute"):
            return None
        filters = [Lead.tenant_id == runtime_input.tenant_id]
        identifiers = []
        if contact_id:
            identifiers.append(Lead.contact_id == contact_id)
        if conversation_id:
            identifiers.append(Lead.conversation_id == conversation_id)
        phone = ActionNodeExecutor._phone_from_runtime_input(runtime_input)
        if phone:
            identifiers.append(Lead.phone == phone)
        if not identifiers:
            return None
        return db.execute(select(Lead).where(*filters, or_(*identifiers))).scalars().first()

    @staticmethod
    def _notification_priority(value: Any) -> str:
        normalized = str(value or "normal").strip().lower()
        aliases = {"low": "low", "baixa": "low", "normal": "normal", "high": "high", "alta": "high"}
        return aliases.get(normalized, "normal")

    @staticmethod
    def _transfer_human(db, *, session: Any, runtime_input: RuntimeInput, params: dict[str, Any]) -> None:
        params = {**params, "mode": "human"}
        ActionNodeExecutor._set_conversation_mode(
            db,
            session=session,
            runtime_input=runtime_input,
            params=params,
            compatibility_action="transfer_human",
        )

    @staticmethod
    def _set_conversation_mode(
        db,
        *,
        session: Any,
        runtime_input: RuntimeInput,
        params: dict[str, Any],
        compatibility_action: str | None = None,
    ) -> None:
        conversation = ActionNodeExecutor._resolve_conversation(db, runtime_input=runtime_input)
        if conversation is None:
            return
        mode = str(params.get("mode") or "").strip().lower()
        context = dict(getattr(conversation, "context", None) or {})
        if compatibility_action == "transfer_human":
            context["transfer_reason"] = str(params.get("reason") or "flow_action")
            conversation.context = context
        set_conversation_mode(
            db,
            tenant_id=session.tenant_id,
            conversation=conversation,
            mode=mode,
            flow_execution_id=getattr(session, "id", None),
            source=compatibility_action or "flow_v2_action",
            reason=str(params.get("reason") or compatibility_action or "flow_action"),
            commit=hasattr(db, "commit"),
            publish_realtime=hasattr(db, "commit"),
        )

    @staticmethod
    def _resolve_contact(db, *, runtime_input: RuntimeInput):
        if runtime_input.contact_id and hasattr(db, "get"):
            contact = db.get(Contact, runtime_input.contact_id)
            if contact is not None and str(getattr(contact, "tenant_id", "")) == str(runtime_input.tenant_id):
                return contact
        phone = ActionNodeExecutor._phone_from_runtime_input(runtime_input)
        if not phone or not hasattr(db, "execute"):
            return None
        return db.execute(
            select(Contact).where(Contact.tenant_id == runtime_input.tenant_id, Contact.phone == phone)
        ).scalars().first()

    @staticmethod
    def _resolve_conversation(db, *, runtime_input: RuntimeInput):
        if runtime_input.conversation_id and hasattr(db, "get"):
            conversation = db.get(Conversation, runtime_input.conversation_id)
            if conversation is not None and str(getattr(conversation, "tenant_id", "")) == str(runtime_input.tenant_id):
                return conversation
        phone = ActionNodeExecutor._phone_from_runtime_input(runtime_input)
        if not phone or not hasattr(db, "execute"):
            return None
        return db.execute(
            select(Conversation).where(Conversation.tenant_id == runtime_input.tenant_id, Conversation.phone_number == phone)
        ).scalars().first()

    @staticmethod
    def _phone_from_runtime_input(runtime_input: RuntimeInput) -> str:
        external_user_id = str(runtime_input.external_user_id or "")
        return external_user_id.split(":", 1)[1] if ":" in external_user_id else external_user_id


class AiRagNodeExecutor(BaseNodeExecutor):
    _INTERNAL_RAG_PLACEHOLDER_RE = re.compile(r"{{\s*(assistant_instruction|chunks|history)\s*}}")

    @classmethod
    def _strip_internal_rag_placeholders(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return cls._INTERNAL_RAG_PLACEHOLDER_RE.sub("", value)

    def _render_rag_public_template(self, value: Any, default: str, db, *, snapshot, session, runtime_input) -> str:
        cleaned = self._strip_internal_rag_placeholders(value)
        rendered = self._render(cleaned if cleaned not in (None, "") else default, db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        text = str(rendered or "").strip()
        return text or default

    @staticmethod
    def _coerce_int_config(value: Any, *, default: int, field_name: str, node_id: str) -> int:
        if value is None or value == "":
            logger.info("[AI RAG NODE] default_used node_id=%s field=%s default=%s reason=missing", node_id, field_name, default)
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            logger.info("[AI RAG NODE] default_used node_id=%s field=%s default=%s invalid_value=%r", node_id, field_name, default, value)
            return default
        if parsed <= 0:
            logger.info("[AI RAG NODE] default_used node_id=%s field=%s default=%s invalid_value=%r", node_id, field_name, default, value)
            return default
        return parsed

    @staticmethod
    def _coerce_float_config(value: Any, *, default: float, field_name: str, node_id: str) -> float:
        if value is None or value == "":
            logger.info("[AI RAG NODE] default_used node_id=%s field=%s default=%s reason=missing", node_id, field_name, default)
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.info("[AI RAG NODE] default_used node_id=%s field=%s default=%s invalid_value=%r", node_id, field_name, default, value)
            return default

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        budget = get_or_create_budget(runtime_input.metadata, session.tenant_id)
        data = self._node_data(node)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, {"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model")})
        instruction = self._render_rag_public_template(data.get("instruction") or data.get("assistant_instruction"), "Responda como atendente.", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        question = self._render_rag_public_template(data.get("question"), "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        fallback = self._render_rag_public_template(data.get("fallback_message"), "Não encontrei essa informação com segurança na base disponível. Quer que eu encaminhe para um atendente?", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        top_k = self._coerce_int_config(data.get("top_k", data.get("topK")), default=5, field_name="top_k", node_id=node_id)
        use_workspace_ai_settings = data.get("use_workspace_ai_settings", data.get("useWorkspaceAiSettings", True)) is not False
        temperature = None if use_workspace_ai_settings else self._coerce_float_config(data.get("temperature"), default=0.2, field_name="temperature", node_id=node_id)
        max_tokens = None if use_workspace_ai_settings else self._coerce_int_config(data.get("max_tokens", data.get("maxTokens")), default=1200, field_name="max_tokens", node_id=node_id)
        behavior = _normalize_ai_rag_after_answer_behavior(data)
        include_sources = data.get("include_sources", data.get("includeSources", False)) is True
        response_style = data.get("response_style", data.get("responseStyle", "whatsapp_short")) or "whatsapp_short"
        memory_enabled = data.get("memory_enabled", data.get("memoryEnabled", True)) is not False
        memory_max_messages = self._coerce_int_config(data.get("memory_max_messages", data.get("memoryMaxMessages")), default=10, field_name="memory_max_messages", node_id=node_id)
        memory_max_chars = self._coerce_int_config(data.get("memory_max_chars", data.get("memoryMaxChars")), default=4000, field_name="memory_max_chars", node_id=node_id)
        knowledge_source_ids = data.get("knowledge_source_ids", data.get("knowledgeSourceIds")) or []
        knowledge_scope = data.get("knowledge_scope", data.get("knowledgeScope"))
        rag_filters = {"source_ids": knowledge_source_ids, "knowledge_scope": knowledge_scope} if knowledge_source_ids else None
        fallback_when_low_confidence = data.get("fallback_when_low_confidence", data.get("fallbackWhenLowConfidence", False)) is True
        min_confidence_level = str(data.get("min_confidence_level", data.get("minConfidenceLevel", "low")) or "low")
        conversation_history = ""
        is_first_ai_turn = True
        session_context = session.context if isinstance(getattr(session, "context", None), dict) else {}
        recent_retrieved_chunks = session_context.get("recent_retrieved_chunks") if isinstance(session_context.get("recent_retrieved_chunks"), list) else []
        flow_id = getattr(snapshot, "flow_id", None)
        if flow_id is None and hasattr(db, "get"):
            flow_version = db.get(FlowVersion, session.flow_version_id)
            flow_id = getattr(flow_version, "flow_id", None)
        if memory_enabled and flow_id is not None:
            flow_ai_memory_service.append_user_message(
                db,
                tenant_id=session.tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                session_id=session.id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                node_id=node_id,
                content=str(question),
                metadata=runtime_input.metadata,
            )
            history_messages = flow_ai_memory_service.get_recent_history(db, tenant_id=session.tenant_id, session_id=session.id, max_messages=memory_max_messages, max_chars=memory_max_chars)
            conversation_history = flow_ai_memory_service.build_history_for_prompt(history_messages)
            is_first_ai_turn = not any(message.role == "assistant" for message in history_messages)
        effective_question = str(question)
        contextual_result = {"standalone_question": effective_question, "used_history": False}
        if not is_greeting(effective_question) and contains_context_reference(effective_question):
            cached = get_cached_standalone(session_context, tenant_id=session.tenant_id, current_question=effective_question)
            if cached:
                contextual_result = cached
            else:
                contextual_result = generate_standalone_question(
                    db,
                    session.tenant_id,
                    effective_question,
                    conversation_history,
                    assistant_instruction=str(instruction),
                )
                store_cached_standalone(session_context, tenant_id=session.tenant_id, current_question=effective_question, result=contextual_result)
            effective_question = str(contextual_result.get("standalone_question") or question)
        logger.info(
            "[CONTEXTUAL QUERY] tenant=%s used_history=%s rewritten=%s history_messages=%s recent_chunks_consulted=%s recent_chunk_hit=false",
            session.tenant_id,
            bool(contextual_result.get("used_history")),
            effective_question != str(question),
            len(conversation_history.splitlines()) if conversation_history else 0,
            len(recent_retrieved_chunks),
        )
        context_builder_meta: dict[str, Any] = {"context_builder_enabled": False, "long_term_memory_count": 0, "long_term_memory_types": [], "memory_latency_ms": 0, "memory_backend": "json_embedding"}
        if context_builder_enabled():
            try:
                ctx = build_context(db, session.tenant_id, contact_id=runtime_input.contact_id, conversation_id=runtime_input.conversation_id, session_id=session.id, current_query=effective_question, include_short_memory=memory_enabled, include_long_memory=True, include_rag_context=False, short_memory_options={"max_messages": memory_max_messages, "max_chars": memory_max_chars})
                cb_section = str(ctx.get("combined_prompt_section") or "")
                if cb_section:
                    conversation_history = cb_section
                context_builder_meta.update({"context_builder_enabled": True, "long_term_memory_count": ctx.get("metadata", {}).get("long_memory_count", 0), "long_term_memory_types": sorted({m.get("fact_type") for m in ctx.get("long_term_memory", []) if m.get("fact_type")}), "memory_latency_ms": ctx.get("metadata", {}).get("memory_latency_ms", 0), "context_builder_fallback_used": ctx.get("metadata", {}).get("fallback_used", False)})
            except Exception as exc:
                logger.warning("[AI RAG NODE] context_builder_failed node_id=%s error=%s", node_id, type(exc).__name__)
        try:
            rag_answer = answer_with_rag(
                db,
                session.tenant_id,
                effective_question,
                system_policy=str(instruction),
                conversation_context=conversation_history,
                is_first_ai_turn=is_first_ai_turn,
                top_k=top_k,
                temperature=temperature,
                chat_model=None if use_workspace_ai_settings else (data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model") or None),
                max_tokens=max_tokens,
                fallback_message=str(fallback),
                include_sources=include_sources,
                response_style=str(response_style),
                filters=rag_filters,
                fallback_when_low_confidence=fallback_when_low_confidence,
                min_confidence_level=min_confidence_level,
                recent_retrieved_chunks=recent_retrieved_chunks,
            )
            now_iso = datetime.now(UTC).isoformat()
            session_context["recent_retrieved_chunks"] = [
                {
                    "chunk_id": c.get("chunk_id"),
                    "source_id": c.get("source_id"),
                    "score": c.get("final_score", c.get("score")),
                    "page": c.get("page") or (c.get("metadata") or {}).get("page"),
                    "source_name": c.get("source_name"),
                    "timestamp": now_iso,
                }
                for c in rag_answer.contexts
                if c.get("chunk_id")
            ][:10]
            session.context = session_context
            if hasattr(db, "add"):
                db.add(session)
            text = rag_answer.answer if rag_answer.found_context else str(fallback)
            metadata = {
                "node_id": node_id,
                "intent": "ai_rag_answer",
                "found_context": rag_answer.found_context,
                "standalone_question_used": effective_question != str(question),
                "source_ids": [c.get("source_id") for c in rag_answer.contexts if c.get("source_id")],
                "chunk_ids": [c.get("chunk_id") for c in rag_answer.contexts if c.get("chunk_id")],
            }
        except Exception as exc:
            logger.warning("[AI RAG NODE] failed node_id=%s error=%s", node_id, exc)
            text = str(fallback)
            metadata = {"node_id": node_id, "intent": "ai_rag_answer", "error": "rag_failed"}
        contexts = locals().get("rag_answer").contexts if "rag_answer" in locals() else []
        sources_count = len(metadata.get("source_ids") or [])
        retrieval_mode = (contexts[0].get("retrieval_mode") if contexts else None) or ("fallback" if metadata.get("error") or not metadata.get("found_context") else "vector")
        fallback_used = not bool(metadata.get("found_context")) or bool(metadata.get("error"))
        confidence = score_confidence(contexts, fallback=fallback_used)
        record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_rag", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="error" if metadata.get("error") else "success", input_text=question, output_text=text, retrieval_mode=retrieval_mode, confidence=confidence, fallback_used=fallback_used, metadata={"prompt_summary": redact_text(instruction), "original_question": redact_text(question), "standalone_question": redact_text(effective_question), "chunks_count": len(contexts), "chunks": [{"chunk_id": c.get("chunk_id"), "source_id": c.get("source_id"), "source_name": c.get("source_name"), "page": c.get("page") or (c.get("metadata") or {}).get("page"), "score": c.get("final_score", c.get("score"))} for c in contexts], "scores": [c.get("final_score", c.get("score")) for c in contexts], "rewrite": effective_question != str(question), "recent_chunk_hit": bool(contexts and contexts[0].get("retrieval_mode") == "recent"), **context_builder_meta})
        logger.info(
            "[AI RAG NODE] flow_id=%s session_id=%s node_id=%s behavior=%s retrieval_mode=%s sources_count=%s answered=%s",
            getattr(snapshot, "flow_id", None) or getattr(session, "flow_id", None),
            session.id,
            node_id,
            behavior,
            retrieval_mode,
            sources_count,
            bool(text),
        )
        self.event_store.append(db, session=session, event_type=FlowV2EventType.MESSAGE_SENT, node_id=node_id, payload={"node_id": node_id, "message": text, "metadata": metadata})
        if memory_enabled and flow_id is not None and text:
            flow_ai_memory_service.append_assistant_message(
                db,
                tenant_id=session.tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                session_id=session.id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                node_id=node_id,
                content=text,
                metadata={"intent": "ai_rag_answer", "found_context": metadata.get("found_context")},
            )
        try:
            
            if runtime_input.conversation_id:
                db.add(ConversationLog(tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, message=str(question)[:1000], mode="flow_v2", intent="ai_rag_answer", response=text[:1000], used_fallback=not metadata.get("found_context", False)))
        except Exception:
            logger.debug("[AI RAG NODE] conversation log skipped", exc_info=True)
        action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, metadata={**runtime_input.metadata, **metadata})
        next_node_id = self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id)
        is_terminal = bool(data.get("is_terminal") or data.get("isTerminal") or data.get("endFlow"))
        if is_terminal or behavior == AiRagAfterAnswerBehavior.END_FLOW:
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        if behavior == AiRagAfterAnswerBehavior.WAIT_SAME_NODE:
            return NodeExecutionResult(actions=(action,), next_node_id=node_id, status="wait")
        if next_node_id is None:
            logger.info("[AI RAG NODE] node_id=%s behavior=continue_to_next next_node_id=None reason=no_outgoing_edge_finishing", node_id)
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        return NodeExecutionResult(actions=(action,), next_node_id=next_node_id, status="continue")


class AiResponseNodeExecutor(AiRagNodeExecutor):
    """Pure LLM response node: tenant AI settings + optional flow memory, no RAG."""

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, {"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model")})
        instruction = self._render_rag_public_template(
            data.get("instruction") or data.get("assistant_instruction"),
            "Responda como atendente.",
            db,
            snapshot=snapshot,
            session=session,
            runtime_input=runtime_input,
        )
        question = self._render_rag_public_template(
            data.get("question") or data.get("input_template") or data.get("inputTemplate"),
            "{{last_message}}",
            db,
            snapshot=snapshot,
            session=session,
            runtime_input=runtime_input,
        )
        behavior = _normalize_ai_rag_after_answer_behavior(data)
        memory_enabled = data.get("memory_enabled", data.get("memoryEnabled", True)) is not False
        memory_max_messages = self._coerce_int_config(data.get("memory_max_messages", data.get("memoryMaxMessages")), default=10, field_name="memory_max_messages", node_id=node_id)
        memory_max_chars = self._coerce_int_config(data.get("memory_max_chars", data.get("memoryMaxChars")), default=4000, field_name="memory_max_chars", node_id=node_id)
        temperature = None if data.get("temperature") in (None, "") else self._coerce_float_config(data.get("temperature"), default=0.2, field_name="temperature", node_id=node_id)
        max_tokens = None if data.get("max_tokens", data.get("maxTokens")) in (None, "") else self._coerce_int_config(data.get("max_tokens", data.get("maxTokens")), default=1200, field_name="max_tokens", node_id=node_id)
        chat_model = data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model") or None

        conversation_history = ""
        is_first_ai_turn = True
        flow_id = getattr(snapshot, "flow_id", None)
        if flow_id is None and hasattr(db, "get"):
            flow_version = db.get(FlowVersion, session.flow_version_id)
            flow_id = getattr(flow_version, "flow_id", None)
        if memory_enabled and flow_id is not None:
            flow_ai_memory_service.append_user_message(
                db,
                tenant_id=session.tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                session_id=session.id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                node_id=node_id,
                content=str(question),
                metadata={**runtime_input.metadata, "intent": "ai_response"},
            )
            history_messages = flow_ai_memory_service.get_recent_history(db, tenant_id=session.tenant_id, session_id=session.id, max_messages=memory_max_messages, max_chars=memory_max_chars)
            conversation_history = flow_ai_memory_service.build_history_for_prompt(history_messages)
            is_first_ai_turn = not any(message.role == "assistant" for message in history_messages)

        context_builder_meta: dict[str, Any] = {"context_builder_enabled": False, "long_term_memory_count": 0, "long_term_memory_types": [], "memory_latency_ms": 0, "memory_backend": "json_embedding", "auto_memory_saved_count": 0}
        context_prompt_section = ""
        if context_builder_enabled():
            try:
                ctx = build_context(db, session.tenant_id, contact_id=runtime_input.contact_id, conversation_id=runtime_input.conversation_id, session_id=session.id, current_query=str(question), include_short_memory=memory_enabled, include_long_memory=True, include_rag_context=False, short_memory_options={"max_messages": memory_max_messages, "max_chars": memory_max_chars})
                context_prompt_section = str(ctx.get("combined_prompt_section") or "")
                context_builder_meta.update({"context_builder_enabled": True, "long_term_memory_count": ctx.get("metadata", {}).get("long_memory_count", 0), "long_term_memory_types": sorted({m.get("fact_type") for m in ctx.get("long_term_memory", []) if m.get("fact_type")}), "memory_latency_ms": ctx.get("metadata", {}).get("memory_latency_ms", 0), "context_builder_fallback_used": ctx.get("metadata", {}).get("fallback_used", False)})
            except Exception as exc:
                logger.warning("[AI RESPONSE NODE] context_builder_failed node_id=%s error=%s", node_id, type(exc).__name__)

        messages: list[dict[str, str]] = [{"role": "system", "content": str(instruction)}]
        if context_prompt_section:
            messages.append({"role": "system", "content": context_prompt_section})
        elif conversation_history:
            messages.append({"role": "system", "content": f"Histórico recente da conversa:\n{conversation_history}"})
        messages.append({"role": "user", "content": str(question)})
        options = {
            key: value
            for key, value in {"chat_model": chat_model, "temperature": temperature, "max_tokens": max_tokens}.items()
            if value not in (None, "")
        }
        try:
            text = generate_answer_for_tenant(db, session.tenant_id, messages, options=options)
            metadata = {
                "node_id": node_id,
                "intent": "ai_response",
                "memory_enabled": memory_enabled,
                "is_first_ai_turn": is_first_ai_turn,
            }
        except Exception as exc:
            logger.warning("[AI RESPONSE NODE] failed node_id=%s error=%s", node_id, exc)
            text = "Não consegui gerar uma resposta agora. Tente novamente em instantes."
            metadata = {"node_id": node_id, "intent": "ai_response", "error": "llm_failed", "memory_enabled": memory_enabled, "is_first_ai_turn": is_first_ai_turn}

        record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_response", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="error" if metadata.get("error") else "success", input_text=question, output_text=text, confidence=None, fallback_used=bool(metadata.get("error")), metadata={"prompt_summary": redact_text(instruction), "history_messages": len(conversation_history.splitlines()) if conversation_history else 0, "memory_enabled": memory_enabled, **context_builder_meta})
        self.event_store.append(db, session=session, event_type=FlowV2EventType.MESSAGE_SENT, node_id=node_id, payload={"node_id": node_id, "message": text, "metadata": metadata})
        if memory_enabled and flow_id is not None and text:
            flow_ai_memory_service.append_assistant_message(
                db,
                tenant_id=session.tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                session_id=session.id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                node_id=node_id,
                content=text,
                metadata={"intent": "ai_response", "is_first_ai_turn": is_first_ai_turn},
            )
        try:
            if runtime_input.conversation_id:
                db.add(ConversationLog(tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, message=str(question)[:1000], mode="flow_v2", intent="ai_response", response=text[:1000], used_fallback=bool(metadata.get("error"))))
        except Exception:
            logger.debug("[AI RESPONSE NODE] conversation log skipped", exc_info=True)
        action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, metadata={**runtime_input.metadata, **metadata})
        next_node_id = self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id)
        if behavior == AiRagAfterAnswerBehavior.END_FLOW:
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        if behavior == AiRagAfterAnswerBehavior.WAIT_SAME_NODE:
            return NodeExecutionResult(actions=(action,), next_node_id=node_id, status="wait")
        if next_node_id is None:
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        return NodeExecutionResult(actions=(action,), next_node_id=next_node_id, status="continue")


class AiAgentNodeExecutor(AiResponseNodeExecutor):
    """Controlled AI agent node with explicit tools only."""

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        if str(data.get("ai_system_internal_type") or "").strip().lower() == "ai_dispatcher":
            return _execute_ai_dispatcher(
                self,
                db,
                snapshot=snapshot,
                session=session,
                node=node,
                runtime_input=runtime_input,
            )
        budget = get_or_create_budget(runtime_input.metadata, session.tenant_id)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, {"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model")})
        instruction = self._render_rag_public_template(data.get("instruction"), "Você é um agente de atendimento. Use apenas as ferramentas permitidas.", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        input_text = self._render_rag_public_template(data.get("input_template") or data.get("inputTemplate") or data.get("question"), "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        behavior = _normalize_ai_rag_after_answer_behavior(data)
        memory_enabled = data.get("use_memory", data.get("useMemory", data.get("memory_enabled", True))) is not False
        memory_max_messages = self._coerce_int_config(data.get("memory_max_messages", data.get("memoryMaxMessages")), default=10, field_name="memory_max_messages", node_id=node_id)
        memory_max_chars = self._coerce_int_config(data.get("memory_max_chars", data.get("memoryMaxChars")), default=4000, field_name="memory_max_chars", node_id=node_id)
        allowed_tools = data.get("allowed_tools") or data.get("allowedTools") or ["responder", "definir_variavel"]
        if not isinstance(allowed_tools, list):
            allowed_tools = ["responder", "definir_variavel"]
        if context_builder_enabled() and runtime_input.contact_id and "salvar_memoria" not in [str(t) for t in allowed_tools]:
            allowed_tools = [*allowed_tools, "salvar_memoria"]
        flow_id = get_flow_id(db, snapshot, session)
        conversation_history = ""
        if memory_enabled and flow_id is not None:
            flow_ai_memory_service.append_user_message(db, tenant_id=session.tenant_id, flow_id=flow_id, flow_version_id=session.flow_version_id, session_id=session.id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, node_id=node_id, content=str(input_text), metadata={**runtime_input.metadata, "intent": "ai_agent"})
            history_messages = flow_ai_memory_service.get_recent_history(db, tenant_id=session.tenant_id, session_id=session.id, max_messages=memory_max_messages, max_chars=memory_max_chars)
            conversation_history = flow_ai_memory_service.build_history_for_prompt(history_messages)
        context_builder_meta: dict[str, Any] = {"context_builder_enabled": False, "long_term_memory_count": 0, "long_term_memory_types": [], "memory_latency_ms": 0, "memory_backend": "json_embedding"}
        if context_builder_enabled():
            try:
                ctx = build_context(db, session.tenant_id, contact_id=runtime_input.contact_id, conversation_id=runtime_input.conversation_id, session_id=session.id, current_query=str(input_text), include_short_memory=memory_enabled, include_long_memory=True, include_rag_context=False, short_memory_options={"max_messages": memory_max_messages, "max_chars": memory_max_chars})
                conversation_history = str(ctx.get("combined_prompt_section") or conversation_history)
                context_builder_meta.update({"context_builder_enabled": True, "long_term_memory_count": ctx.get("metadata", {}).get("long_memory_count", 0), "long_term_memory_types": sorted({m.get("fact_type") for m in ctx.get("long_term_memory", []) if m.get("fact_type")}), "memory_latency_ms": ctx.get("metadata", {}).get("memory_latency_ms", 0), "context_builder_fallback_used": ctx.get("metadata", {}).get("fallback_used", False)})
            except Exception as exc:
                logger.warning("[AI AGENT NODE] context_builder_failed node_id=%s error=%s", node_id, type(exc).__name__)
        allow_node_tools = data.get("allow_node_tools", data.get("allowNodeTools", False)) is True
        node_tools = data.get("node_tools", data.get("nodeTools", [])) if allow_node_tools else []
        if not isinstance(node_tools, list):
            node_tools = []
        max_node_tool_calls = self._coerce_int_config(data.get("max_node_tool_calls", data.get("maxNodeToolCalls")), default=3, field_name="max_node_tool_calls", node_id=node_id)
        max_node_tool_calls = min(max(max_node_tool_calls, 1), 5)
        if allow_node_tools and "executar_node" not in [str(t) for t in allowed_tools]:
            allowed_tools = [*allowed_tools, "executar_node"]
        allow_subflow_tools = data.get("allow_subflow_tools", data.get("allowSubflowTools", False)) is True
        subflow_tools = data.get("subflow_tools", data.get("subflowTools", [])) if allow_subflow_tools else []
        if not isinstance(subflow_tools, list):
            subflow_tools = []
        max_subflow_calls = self._coerce_int_config(data.get("max_subflow_calls", data.get("maxSubflowCalls")), default=2, field_name="max_subflow_calls", node_id=node_id)
        max_subflow_calls = min(max(max_subflow_calls, 1), 3)
        if allow_subflow_tools and "executar_subflow" not in [str(t) for t in allowed_tools]:
            allowed_tools = [*allowed_tools, "executar_subflow"]
        allow_mcp_tools = data.get("allow_mcp_tools", data.get("allowMcpTools", False)) is True
        raw_mcp_tool_ids = data.get("mcp_tool_ids", data.get("mcpToolIds", [])) if allow_mcp_tools else []
        if not isinstance(raw_mcp_tool_ids, list):
            raw_mcp_tool_ids = []
        mcp_tool_ids = [str(item) for item in raw_mcp_tool_ids if item]
        mcp_tools = []
        if allow_mcp_tools and mcp_tool_ids:
            from app.models.tenant_mcp import TenantMCPTool
            from app.services.google_calendar_service import PROVIDER as GOOGLE_CALENDAR_PROVIDER
            from app.services.integration_connection_service import IntegrationConnectionService
            from app.tools.adapters.google_calendar_tool_adapter import GOOGLE_CALENDAR_TOOL_IDS, google_calendar_tool_definitions
            from sqlalchemy import select
            import uuid as _uuid
            parsed_ids = []
            internal_google_ids = []
            for item in mcp_tool_ids:
                if str(item) in GOOGLE_CALENDAR_TOOL_IDS:
                    internal_google_ids.append(str(item))
                    continue
                try:
                    parsed_ids.append(_uuid.UUID(str(item)))
                except ValueError:
                    continue
            if parsed_ids:
                rows = db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == session.tenant_id, TenantMCPTool.id.in_(parsed_ids), TenantMCPTool.is_enabled.is_(True))).scalars().all()
                mcp_tools = [{"tool_id": str(row.id), "name": row.display_name or row.tool_name, "description": row.description, "input_schema": row.input_schema or {}, "source": "MCP"} for row in rows]
            if internal_google_ids and IntegrationConnectionService(db).get_active_connection(session.tenant_id, GOOGLE_CALENDAR_PROVIDER) is not None:
                google_tools = [tool for tool in google_calendar_tool_definitions(connected=True) if str(tool.get("tool_id")) in internal_google_ids]
                mcp_tools.extend(google_tools)
        max_mcp_calls = self._coerce_int_config(data.get("max_mcp_calls", data.get("maxMcpCalls")), default=3, field_name="max_mcp_calls", node_id=node_id)
        max_mcp_calls = min(max(max_mcp_calls, 0), 3)
        if allow_mcp_tools and mcp_tools and "chamar_mcp" not in [str(t) for t in allowed_tools]:
            allowed_tools = [*allowed_tools, "chamar_mcp"]
        logger.info("event=NODE_ALLOWED_TOOLS %s", json.dumps({"node_id": str(node_id), "mcp_tool_ids": mcp_tool_ids, "internal_google_tools": [str(t.get("tool_id") or t.get("id")) for t in mcp_tools if str(t.get("tool_id") or t.get("id") or "").startswith("google_calendar_")], "final_allowed_tools": [str(t) for t in allowed_tools], "available_mcp_tools": [str(t.get("tool_id") or t.get("id")) for t in mcp_tools]}, ensure_ascii=False, default=str))
        session_state = session.context if isinstance(getattr(session, "context", None), dict) else {}
        session_state.setdefault("session_id", str(session.id))
        options = {
            "chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model"),
            "temperature": self._coerce_float_config(data.get("temperature"), default=0.2, field_name="temperature", node_id=node_id),
            "max_tokens": self._coerce_int_config(data.get("max_tokens", data.get("maxTokens")), default=1200, field_name="max_tokens", node_id=node_id),
            "max_steps": self._coerce_int_config(data.get("max_steps", data.get("maxSteps")), default=3, field_name="max_steps", node_id=node_id),
            "fallback_message": data.get("fallback_message") or data.get("fallbackMessage"),
            "max_node_tool_calls": max_node_tool_calls,
            "max_subflow_calls": max_subflow_calls,
            "max_mcp_calls": max_mcp_calls,
            "node_id": node_id,
            "selected_tool_ids": mcp_tool_ids,
            "session_state": session_state,
        }
        def _execute_agent_node_tool(tool_config, tool_input, reason):
            from app.services.ai_agent_node_tool_service import execute_node_tool
            return execute_node_tool(session.tenant_id, snapshot, session, node_id, tool_config, tool_input, runtime_input, db, budget=budget)
        def _execute_agent_subflow_tool(tool_config, tool_input, reason):
            from app.services.ai_agent_subflow_tool_service import execute_subflow_tool
            return execute_subflow_tool(session.tenant_id, flow_id, session.id, node_id, tool_config, tool_input, runtime_input, db, budget=budget)
        def _execute_agent_mcp_tool(tool_config, tool_input):
            from app.services.mcp_service import call_mcp_tool
            return call_mcp_tool(db, session.tenant_id, str(tool_config.get("tool_id")), tool_input, timeout_seconds=15, budget=budget)
        result = run_agent_for_tenant(db, session.tenant_id, str(input_text), str(instruction), [str(t) for t in allowed_tools], {"webhooks": data.get("webhooks") or [], "node_tools": node_tools, "subflow_tools": subflow_tools, "mcp_tools": mcp_tools, "memory_context": {"contact_id": runtime_input.contact_id, "conversation_id": runtime_input.conversation_id, "session_id": session.id}}, memory_context=conversation_history, options=options, node_tool_executor=_execute_agent_node_tool if allow_node_tools else None, subflow_tool_executor=_execute_agent_subflow_tool if allow_subflow_tools else None, mcp_tool_executor=_execute_agent_mcp_tool if allow_mcp_tools else None, budget=budget)
        persist_budget(runtime_input.metadata, budget)
        actions: list[RuntimeAction] = []
        context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else {}
        for agent_action in result.actions:
            if agent_action.type == "set_variable":
                _set_nested_value(context, str(agent_action.data.get("name")), agent_action.data.get("value"))
            elif agent_action.type == "message":
                actions.append(SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=str(agent_action.data.get("message") or ""), metadata={**runtime_input.metadata, "node_id": node_id, "intent": "ai_agent"}))
        session.context = context
        if hasattr(db, "add") and sqlalchemy_inspect(session, raiseerr=False) is not None:
            db.add(session)
        metadata = {"tools_allowed": [str(t) for t in allowed_tools], "node_tools_allowed": [{"tool_id": str(t.get("tool_id")), "node_id": str(t.get("node_id")), "label": str(t.get("label", ""))[:80]} for t in node_tools if isinstance(t, dict)], "tools_used": result.tools_used, "mcp_tools_allowed": mcp_tools, "mcp_tools_used": result.metadata.get("mcp_tools_used", []), "mcp_call_count": result.metadata.get("mcp_call_count", 0), "mcp_latency_ms": result.metadata.get("mcp_latency_ms", 0), "mcp_status": result.metadata.get("mcp_status", "not_used"), "mcp_error_sanitized": result.metadata.get("mcp_error_sanitized"), "node_tools_used": result.metadata.get("node_tools_used", []), "subflow_tools_allowed": [{"tool_id": str(t.get("tool_id")), "flow_id": str(t.get("flow_id")), "label": str(t.get("label", ""))[:80]} for t in subflow_tools if isinstance(t, dict)], "subflow_tools_used": result.metadata.get("subflow_tools_used", []), "subflow_calls_count": result.metadata.get("subflow_calls_count", 0), "subflow_results_summary": result.metadata.get("subflow_results_summary", []), "subflow_errors": result.metadata.get("subflow_errors", []), "timeout_count": result.metadata.get("timeout_count", 0), "parent_session_id": str(session.id), "subflow_session_ids": [], "node_tool_calls_count": result.metadata.get("node_tool_calls_count", 0), "node_tool_results_summary": result.metadata.get("node_tools_used", []), "blocked_tool_calls": result.metadata.get("blocked_tool_calls", []), "max_steps_reached": result.metadata.get("max_steps_reached", False), "steps_count": result.steps_count, "final_tool": result.final_tool, "status": result.status, "webhook_count": len(data.get("webhooks") or []), "latency_ms": result.metadata.get("latency_ms"), **context_builder_meta, "auto_memory_saved_count": result.metadata.get("memory_saved_count", 0), **budget.safe_metadata()}
        record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=flow_id, flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_agent", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status=result.status, input_text=input_text, output_text=result.message, fallback_used=result.fallback_used, metadata=metadata)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_agent_completed", **metadata})
        if memory_enabled and flow_id is not None and result.message:
            flow_ai_memory_service.append_assistant_message(db, tenant_id=session.tenant_id, flow_id=flow_id, flow_version_id=session.flow_version_id, session_id=session.id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, node_id=node_id, content=result.message, metadata={"intent": "ai_agent"})
        next_node_id = self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id)
        if behavior == AiRagAfterAnswerBehavior.END_FLOW:
            return NodeExecutionResult(actions=tuple(actions), next_node_id=None, status="complete")
        if behavior == AiRagAfterAnswerBehavior.WAIT_SAME_NODE:
            return NodeExecutionResult(actions=tuple(actions), next_node_id=node_id, status="wait")
        return NodeExecutionResult(actions=tuple(actions), next_node_id=next_node_id, status="continue" if next_node_id else "complete")


AI_DISPATCHER_VALID_INTENTS = {
    "greeting",
    "calendar_create",
    "calendar_list",
    "calendar_delete",
    "support_question",
    "sales_lead",
    "rag_question",
    "human_handoff",
    "unknown",
}

AI_DISPATCHER_INTENT_ALIASES = {
    "calendar": "calendar_create",
    "schedule": "calendar_create",
    "createevent": "calendar_create",
    "create_event": "calendar_create",
    "createcalendarevent": "calendar_create",
    "create_calendar_event": "calendar_create",
    "calendarcreate": "calendar_create",
    "scheduleevent": "calendar_create",
    "schedule_event": "calendar_create",
    "agendamento": "calendar_create",
    "agendar": "calendar_create",
    "agende": "calendar_create",
}


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def _normalize_dispatcher_text(value: str) -> str:
    return _strip_accents(value or "").strip().lower()


def _matched_terms(text: str, patterns: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matches.append(pattern)
    return matches


def _normalize_ai_dispatcher_intent(value: Any) -> str:
    """Normalize dispatcher LLM/tool outputs into a supported source handle."""

    candidate: Any = value
    if isinstance(candidate, str):
        stripped = candidate.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                candidate = json.loads(stripped)
            except json.JSONDecodeError:
                candidate = stripped
        else:
            candidate = stripped
    if isinstance(candidate, dict):
        arguments = candidate.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"text": arguments}
        if isinstance(arguments, dict):
            for key in ("intent", "text", "mensagem"):
                if arguments.get(key) is not None:
                    candidate = arguments.get(key)
                    break
        elif candidate.get("intent") is not None:
            candidate = candidate.get("intent")
        elif candidate.get("text") is not None:
            candidate = candidate.get("text")
        elif candidate.get("mensagem") is not None:
            candidate = candidate.get("mensagem")
    normalized = _normalize_dispatcher_text(str(candidate or ""))
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    normalized = AI_DISPATCHER_INTENT_ALIASES.get(normalized, normalized)
    return normalized if normalized in AI_DISPATCHER_VALID_INTENTS else "unknown"


def _agent_system_message_intent_details(message: str) -> dict[str, Any]:
    text = _normalize_dispatcher_text(message)
    calendar_keywords = (
        r"\bmarque\b", r"\bmarcar\b", r"\bagenda\b", r"\bagende\b", r"\bagendar\b",
        r"\breservar\b", r"\bcriar\s+reuniao\b", r"\bcall\b", r"\breuniao\b",
        r"\bcompromisso\b", r"\bconsultoria\b", r"\bhorario\b", r"\bdisponibilidade\b",
    )
    time_signals = (
        r"\bamanha\b", r"\bhoje\b", r"\bdepois\s+de\s+amanha\b", r"\bdia\b",
        r"\bas\b", r"\bàs\b", r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2}h(?:\d{2})?\b",
        r"\b\d{1,2}\s+horas\b", r"\bmanha\b", r"\btarde\b", r"\bnoite\b",
    )
    availability_patterns = (
        r"\btem\s+horario\b", r"\btenho\s+horario\b", r"\bqual\s+(?:a\s+)?disponibilidade\b",
        r"\bhorarios\s+livres\b", r"\blivre\s+amanha\b", r"\bhorario\s+livre\b",
    )
    delete_patterns = (r"\bcancel", r"\bdesmarc", r"\bexcluir\s+evento\b", r"\bremover\s+evento\b")

    matched_keywords = _matched_terms(text, calendar_keywords)
    matched_time_signals = _matched_terms(text, time_signals)
    matched_availability = _matched_terms(text, availability_patterns)
    partial_create_patterns = (
        r"\b(?:gostaria|quero|preciso)\s+de\s+marcar\s+(?:uma\s+)?consultoria\b",
        r"\bmarcar\s+(?:uma\s+)?consultoria\b",
        r"\bagendar\s+(?:uma\s+)?consultoria\b",
        r"\bconsultoria\s+com\s+\w+",
    )
    matched_partial_create = _matched_terms(text, partial_create_patterns)
    matched_delete = _matched_terms(text, delete_patterns)
    intent = "unknown"
    confidence = 0.0

    if matched_delete and (matched_time_signals or matched_keywords or "reuniao" in text):
        intent = "calendar_delete"
        confidence = 0.95
    elif matched_availability:
        intent = "calendar_list"
        confidence = 0.9
    elif matched_keywords and matched_time_signals:
        intent = "calendar_create"
        confidence = 0.95
    elif matched_partial_create:
        intent = "calendar_create"
        confidence = 0.88
    elif re.fullmatch(r"(oi+|ola|bom dia|boa tarde|boa noite|hey|hello|hi)[!?.\s]*", text):
        intent = "greeting"
        confidence = 0.9
    elif any(term in text for term in ("atendente", "humano", "pessoa")):
        intent = "human_handoff"
        confidence = 0.8
    elif any(term in text for term in ("preco", "plano", "comprar", "orcamento", "vendas")):
        intent = "sales_lead"
        confidence = 0.8
    elif any(term in text for term in ("suporte", "ajuda", "problema", "duvida")):
        intent = "support_question"
        confidence = 0.8

    logger.info(
        "event=AI_DISPATCHER_DETERMINISTIC_INTENT text=%s matched_keywords=%s matched_time_signals=%s intent=%s confidence=%s",
        (message or "")[:500], matched_keywords + matched_availability + matched_delete + matched_partial_create, matched_time_signals, intent, confidence,
    )
    return {"intent": intent, "text": (message or "")[:500], "matched_keywords": matched_keywords + matched_availability + matched_delete + matched_partial_create, "matched_time_signals": matched_time_signals, "confidence": confidence}


def _agent_system_message_intent(message: str) -> str:
    return str(_agent_system_message_intent_details(message).get("intent") or "unknown")


def _execute_ai_dispatcher(executor: BaseNodeExecutor, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
    node_id = str(node["id"])
    context = session.context if isinstance(getattr(session, "context", None), dict) else {}
    logger.info("event=AI_SYSTEM_PENDING_EVENT_LOOKUP node_id=%s context_keys=%s", node_id, sorted(context.keys()))
    pending_key, pending_payload = pending_event_lookup(context)
    if pending_payload is not None:
        logger.info("event=AI_SYSTEM_PENDING_EVENT_FOUND node_id=%s key=%s", node_id, pending_key)
        if message_has_date_or_time(runtime_input.message_text or ""):
            deterministic = {"intent": "calendar_create", "text": (runtime_input.message_text or "")[:500], "matched_keywords": ["pending_event"], "matched_time_signals": ["pending_event_continuation"], "confidence": 1.0}
        else:
            deterministic = _agent_system_message_intent_details(runtime_input.message_text or "")
    else:
        logger.info("event=AI_SYSTEM_PENDING_EVENT_NOT_FOUND node_id=%s context_keys=%s", node_id, sorted(context.keys()))
        deterministic = _agent_system_message_intent_details(runtime_input.message_text or "")
    executor.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_DISPATCHER_DETERMINISTIC_INTENT", **deterministic})
    raw_intent = deterministic.get("intent") or "unknown"
    intent = _normalize_ai_dispatcher_intent(raw_intent)
    logger.info("event=AI_DISPATCHER_INTENT_DETECTED node_id=%s intent=%s raw_intent=%s", node_id, intent, raw_intent)
    executor.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_DISPATCHER_INTENT_DETECTED", "intent": intent, "raw_intent": raw_intent})
    logger.info("event=AI_DISPATCHER_SOURCE_HANDLE_SELECTED node_id=%s source_handle=%s", node_id, intent)
    executor.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_DISPATCHER_SOURCE_HANDLE_SELECTED", "intent": intent, "source_handle": intent})

    selected_handle = intent
    transitions = executor.transition_resolver._snapshot_transitions(snapshot)
    intent_matches = executor.transition_resolver._matches(transitions=transitions, source_node_id=node_id, source_handle=intent)
    if not intent_matches and intent != "unknown":
        unknown_matches = executor.transition_resolver._matches(transitions=transitions, source_node_id=node_id, source_handle="unknown")
        if unknown_matches:
            selected_handle = "unknown"
            logger.info("event=AI_DISPATCHER_UNKNOWN_FALLBACK node_id=%s intent=%s fallback_source_handle=unknown", node_id, intent)
    resolution = executor.transition_resolver.resolve(db, snapshot=snapshot, session=session, source_node_id=node_id, source_handle=selected_handle)
    next_node_id = resolution.target_node_id
    logger.info("event=AI_DISPATCHER_ROUTED node_id=%s intent=%s source_handle=%s next_node_id=%s", node_id, intent, selected_handle, next_node_id)
    executor.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_DISPATCHER_ROUTED", "intent": intent, "source_handle": selected_handle, "next_node_id": next_node_id})
    return NodeExecutionResult(next_node_id=next_node_id, status="continue" if next_node_id else "complete", next_source_handle=selected_handle, intent=intent)


class AiDispatcherNodeExecutor(BaseNodeExecutor):
    """Deterministic first-pass intent router for agent system templates."""

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        return _execute_ai_dispatcher(self, db, snapshot=snapshot, session=session, node=node, runtime_input=runtime_input)


class AiGreetingNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        logger.info("event=AI_SPECIALIZED_AGENT_STARTED node_id=%s node_type=ai_greeting", node_id)
        action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text="Olá! 👋 Como posso ajudar?", metadata={**runtime_input.metadata, "node_id": node_id, "intent": "ai_greeting"})
        logger.info("event=AI_SPECIALIZED_AGENT_FINISHED node_id=%s node_type=ai_greeting", node_id)
        return NodeExecutionResult(actions=(action,), next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="complete")


class AiSafeFallbackNodeExecutor(BaseNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        text = str(data.get("fallback_message") or data.get("instruction") or "Não consegui entender totalmente. Você quer agendar algo, tirar uma dúvida ou falar com um atendente?")
        context = session.context if isinstance(getattr(session, "context", None), dict) else {}
        _, pending_payload = pending_event_lookup(context)
        logger.info("event=AI_SYSTEM_FALLBACK_CONTEXT_KEYS node_id=%s context_keys=%s", node_id, sorted(context.keys()))
        logger.info("event=AI_SYSTEM_FALLBACK_PENDING_EVENT_PRESENT node_id=%s present=%s", node_id, pending_payload is not None)
        logger.info("event=AI_SAFE_FALLBACK_USED node_id=%s", node_id)
        action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, metadata={**runtime_input.metadata, "node_id": node_id, "intent": "ai_safe_fallback"})
        return NodeExecutionResult(actions=(action,), next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="complete")


class AiCalendarAgentNodeExecutor(AiAgentNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        logger.info("event=AI_SPECIALIZED_AGENT_STARTED node_id=%s node_type=ai_calendar_agent", node_id)
        wrapped = dict(node)
        data = dict(self._node_data(node))
        data.setdefault("instruction", "Você é um agente especializado em agenda. Use Google Calendar apenas quando necessário. Nunca confirme evento sem retorno real da ferramenta. Use o DateResolver determinístico.")
        data["allow_mcp_tools"] = True
        data.setdefault("mcp_tool_ids", ["google_calendar_create_event", "google_calendar_list_events", "google_calendar_delete_event"])
        data.setdefault("allowed_tools", ["responder", "chamar_mcp"])
        data.setdefault("after_agent_behavior", "end_flow")
        wrapped["data"] = data
        result = super().execute(db, snapshot=snapshot, session=session, node=wrapped, runtime_input=runtime_input)
        logger.info("event=AI_SPECIALIZED_AGENT_FINISHED node_id=%s node_type=ai_calendar_agent status=%s", node_id, result.status)
        return result


class AiSupervisorNodeExecutor(AiResponseNodeExecutor):
    """Supervisor node that routes one request to one existing IA Agente."""

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        budget = get_or_create_budget(runtime_input.metadata, session.tenant_id)
        data = self._node_data(node)
        stack = list(runtime_input.metadata.get("supervisor_stack") or [])
        if node_id in stack or len(stack) >= MAX_SUPERVISOR_DEPTH:
            action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=SUPERVISOR_FALLBACK_MESSAGE, metadata={**runtime_input.metadata, "node_id": node_id, "intent": "ai_supervisor", "recursion_blocked": True})
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        input_text = self._render_rag_public_template(data.get("input_template") or data.get("inputTemplate") or "{{last_message}}", "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        selected_ids = data.get("agent_ids") or data.get("agentIds") or data.get("agents") or []
        if not isinstance(selected_ids, list):
            selected_ids = []
        agents = build_available_agents(snapshot, node_id, selected_ids)
        fallback_agent_id = str(data.get("fallback_agent_id") or data.get("fallbackAgentId") or "") or None
        ctx = get_supervisor_context(db, session.tenant_id, contact_id=runtime_input.contact_id, conversation_id=runtime_input.conversation_id, session_id=session.id, current_query=str(input_text), memory_max_messages=self._coerce_int_config(data.get("memory_max_messages", data.get("memoryMaxMessages")), default=10, field_name="memory_max_messages", node_id=node_id), memory_max_chars=self._coerce_int_config(data.get("memory_max_chars", data.get("memoryMaxChars")), default=4000, field_name="memory_max_chars", node_id=node_id))
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, {"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model")})
        try:
            budget.enter_depth()
            budget.consume_llm_call(prompt_tokens_estimate=(len(str(input_text)) + len(str(ctx.get("combined_prompt_section") or ""))) // 4, completion_tokens_estimate=180)
        except ExecutionBudgetExceeded:
            persist_budget(runtime_input.metadata, budget)
            metadata = {"selected_agent": None, "fallback_used": True, "budget_exceeded": True, **budget.safe_metadata()}
            action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=SUPERVISOR_FALLBACK_MESSAGE, metadata={**runtime_input.metadata, **metadata, "node_id": node_id, "intent": "ai_supervisor"})
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        decision = decide_supervisor_agent(db, session.tenant_id, message=str(input_text), supervisor_prompt=str(data.get("supervisor_prompt") or data.get("prompt") or ""), agents=agents, context_section=str(ctx.get("combined_prompt_section") or ""), fallback_agent_id=fallback_agent_id, options={"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model"), "temperature": 0, "max_tokens": 180})
        selected_agent = decision.selected_agent
        fallback_used = decision.fallback_used
        budget.exit_depth()
        persist_budget(runtime_input.metadata, budget)
        metadata = {"selected_agent": selected_agent, "selection_latency": decision.latency_ms, "selection_reason": decision.reason[:240], "fallback_used": fallback_used, "supervisor_execution": True, "available_agents_count": len(agents), "context_builder_enabled": True, "long_term_memory_count": ctx.get("metadata", {}).get("long_memory_count", 0), "memory_latency_ms": ctx.get("metadata", {}).get("memory_latency_ms", 0), **budget.safe_metadata()}
        if not selected_agent:
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_supervisor", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="fallback", input_text=input_text, output_text=SUPERVISOR_FALLBACK_MESSAGE, fallback_used=True, metadata=metadata)
            action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=SUPERVISOR_FALLBACK_MESSAGE, metadata={**runtime_input.metadata, **metadata, "node_id": node_id, "intent": "ai_supervisor"})
            return NodeExecutionResult(actions=(action,), next_node_id=None, status="complete")
        target = snapshot.node_by_id.get(selected_agent)
        if not isinstance(target, dict):
            return NodeExecutionResult(actions=(), next_node_id=None, status="complete")
        original_context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else None
        sub_input = RuntimeInput(**{**runtime_input.__dict__, "metadata": {**runtime_input.metadata, "supervisor_stack": [*stack, node_id], "supervisor_execution": True, "supervisor_node_id": node_id}})
        try:
            result = AiAgentNodeExecutor(event_store=self.event_store, transition_resolver=self.transition_resolver).execute(db, snapshot=snapshot, session=session, node=target, runtime_input=sub_input)
        finally:
            if original_context is not None:
                session.context = original_context
                if hasattr(db, "add"):
                    db.add(session)
        record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_supervisor", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="success", input_text=input_text, output_text="", fallback_used=fallback_used, metadata=metadata)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_supervisor_completed", **metadata})
        return NodeExecutionResult(actions=result.actions, next_node_id=None, status="complete")


def _set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path or "").split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


class AiSummaryNodeExecutor(BaseNodeExecutor):
    def _save_text(self, db, *, session, output_variable: str, text: str) -> None:
        context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else {}
        _set_nested_value(context, "ai.summary", text)
        _set_nested_value(context, output_variable, text)
        session.context = context
        if hasattr(db, "add") and sqlalchemy_inspect(session, raiseerr=False) is not None:
            db.add(session)

    def _save_error(self, db, *, session, node_id: str, error: str) -> None:
        context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else {}
        _set_nested_value(context, "ai.error", {"node_id": node_id, "error": error})
        session.context = context
        if hasattr(db, "add") and sqlalchemy_inspect(session, raiseerr=False) is not None:
            db.add(session)

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, {"chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model")})
        continue_on_error = data.get("continue_on_error", data.get("continueOnError", True)) is not False
        try:
            source = str(data.get("summary_source", data.get("summarySource", "conversation_history")) or "conversation_history").strip().lower()
            if source == "custom_text":
                source_text = str(self._render(data.get("input_template") or data.get("inputTemplate") or "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input) or "")
            else:
                max_messages = self._coerce_int(data.get("max_history_messages", data.get("maxHistoryMessages")), default=30)
                max_chars = self._coerce_int(data.get("max_history_chars", data.get("maxHistoryChars")), default=8000)
                history = flow_ai_memory_service.get_recent_history(db, tenant_id=session.tenant_id, session_id=session.id, max_messages=max_messages, max_chars=max_chars)
                source_text = flow_ai_memory_service.build_history_for_prompt(history)
                if not source_text.strip() and runtime_input.message_text:
                    source_text = str(runtime_input.message_text)

            options = {
                key: value
                for key, value in {
                    "chat_model": data.get("chat_model_override") or data.get("chat_model") or data.get("model_override") or data.get("model"),
                    "temperature": self._coerce_float(data.get("temperature"), default=0.2) if data.get("temperature") not in (None, "") else 0.2,
                    "max_tokens": self._coerce_int(data.get("max_tokens", data.get("maxTokens")), default=800) if data.get("max_tokens", data.get("maxTokens")) not in (None, "") else 800,
                }.items()
                if value not in (None, "")
            }
            text = summarize_for_tenant(
                db,
                session.tenant_id,
                source_text,
                instruction=data.get("instruction"),
                summary_format=str(data.get("summary_format", data.get("summaryFormat", "handoff")) or "handoff"),
                options=options,
            )
            output_variable = str(data.get("output_variable") or data.get("outputVariable") or "ai.summary")
            self._save_text(db, session=session, output_variable=output_variable, text=text)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_summary", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="success", input_text=source_text, output_text=text, metadata={"summary_format": str(data.get("summary_format", data.get("summaryFormat", "handoff")) or "handoff"), "summary_source": source, "history_messages": len(source_text.splitlines()) if source_text else 0, "history_chars": len(source_text or "")})
            self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_summary_completed", "output_variable": output_variable, "source": source})
            actions = ()
            if data.get("send_message", data.get("sendMessage", False)) is True:
                actions = (SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, metadata={"node_id": node_id, "intent": "ai_summary"}),)
            return NodeExecutionResult(actions=actions, next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="continue")
        except Exception as exc:
            logger.warning("[AI SUMMARY NODE] failed node_id=%s error=%s", node_id, exc)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_summary", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="error", fallback_used=True, metadata={"error": "ai_summary_failed"})
            self._save_error(db, session=session, node_id=node_id, error="ai_summary_failed")
            self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_summary_failed", "error": "ai_summary_failed"})
            if continue_on_error:
                return NodeExecutionResult(next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="continue")
            return NodeExecutionResult(next_node_id=None, status="error")

    @staticmethod
    def _coerce_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


class AiStructuredNodeExecutor(BaseNodeExecutor):
    kind = "ai_structured"

    def _save_result(self, db, *, session, output_variable: str, result: dict[str, Any]) -> None:
        context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else {}
        # The named output of a classifier is its category.  Keep the historical
        # ai.classification object for existing flows, while making custom output
        # variables directly consumable by Runtime V2 conditions.
        _set_nested_value(
            context,
            output_variable,
            result if output_variable == "ai.classification" else result.get("category"),
        )
        if output_variable == "ai.classification":
            _set_nested_value(context, "ai.classification.category", result.get("category"))
            _set_nested_value(context, "ai.classification.confidence", result.get("confidence"))
            _set_nested_value(context, "ai.classification.reason", result.get("reason"))
        if output_variable == "ai.extraction":
            for key, value in (result.get("data") or {}).items():
                _set_nested_value(context, f"ai.extraction.data.{key}", value)
            _set_nested_value(context, "ai.extraction.missing_fields", result.get("missing_fields"))
            _set_nested_value(context, "ai.extraction.confidence", result.get("confidence"))
        session.context = context
        if hasattr(db, "add") and sqlalchemy_inspect(session, raiseerr=False) is not None:
            db.add(session)

    def _fail(self, db, *, snapshot, session, node_id: str, error: str) -> NodeExecutionResult:
        context = dict(session.context or {}) if isinstance(getattr(session, "context", None), dict) else {}
        _set_nested_value(context, "ai.error", {"node_id": node_id, "error": error})
        session.context = context
        if hasattr(db, "add") and sqlalchemy_inspect(session, raiseerr=False) is not None:
            db.add(session)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_structured_failed", "error": error})
        return NodeExecutionResult(next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="continue")


class AiClassificationNodeExecutor(AiStructuredNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, None)
        try:
            input_text = str(self._render(data.get("input_template") or data.get("inputTemplate") or "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input) or "")
            result = classify_for_tenant(db, session.tenant_id, input_text, data.get("categories") or [], instruction=data.get("instruction"), options={"allow_other": data.get("allow_other", data.get("allowOther", True)), "confidence_threshold": data.get("confidence_threshold", data.get("confidenceThreshold", 0.6))})
            categories = {str(item) for item in (data.get("categories") or [])}
            threshold = float(data.get("confidence_threshold", data.get("confidenceThreshold", 0.6)) or 0.6)
            category = str(result.get("category") or "").strip()
            confidence = float(result.get("confidence") or 0)
            if not category or category not in categories or confidence < threshold:
                result = {
                    **result,
                    "category": str(data.get("fallback") or "outro"),
                    "reason": result.get("reason") or "classification_fallback",
                }
            self._save_result(db, session=session, output_variable=str(data.get("output_variable") or data.get("outputVariable") or "ai.classification"), result=result)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_classification", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="success", input_text=input_text, output_text=result.get("category"), confidence=result.get("confidence"), fallback_used=str(result.get("category")) == "outro" or float(result.get("confidence") or 0) < float(threshold or 0), metadata={"category": result.get("category"), "threshold": threshold})
            self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_classification_completed", "category": result.get("category"), "confidence": result.get("confidence")})
            actions = ()
            if data.get("send_debug_message") is True or data.get("sendDebugMessage") is True:
                actions = (SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=f"IA Classificação: {result.get('category')} ({result.get('confidence')})", metadata={"node_id": node_id, "intent": "ai_classification_debug"}),)
            return NodeExecutionResult(actions=actions, next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="continue")
        except Exception as exc:
            logger.warning("[AI STRUCTURED NODE] classification failed node_id=%s error=%s", node_id, exc)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_classification", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="error", fallback_used=True, metadata={"error": "ai_classification_failed"})
            self._save_result(
                db,
                session=session,
                output_variable=str(data.get("output_variable") or data.get("outputVariable") or "ai.classification"),
                result={"category": str(data.get("error_fallback") or data.get("fallback") or "outro"), "confidence": 0.0, "reason": "ai_classification_failed"},
            )
            return self._fail(db, snapshot=snapshot, session=session, node_id=node_id, error="ai_classification_failed")


class AiExtractionNodeExecutor(AiStructuredNodeExecutor):
    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        ai_started_at = datetime.now(UTC)
        ai_config = resolve_ai_config(db, session.tenant_id, None)
        try:
            input_text = str(self._render(data.get("input_template") or data.get("inputTemplate") or "{{last_message}}", db, snapshot=snapshot, session=session, runtime_input=runtime_input) or "")
            history = None
            if data.get("include_conversation_history", data.get("includeConversationHistory", True)) is not False:
                history = str((session.context or {}).get("conversation_history") or "") if isinstance(session.context, dict) else ""
            result = extract_for_tenant(db, session.tenant_id, input_text, data.get("fields") or [], instruction=data.get("instruction"), conversation_history=history, options={})
            self._save_result(db, session=session, output_variable=str(data.get("output_variable") or data.get("outputVariable") or "ai.extraction"), result=result)
            found_fields = [k for k, v in (result.get("data") or {}).items() if v not in (None, "")]
            memory_saved_count = 0
            if data.get("enable_long_term_memory", data.get("enableLongTermMemory", False)) is True and runtime_input.contact_id:
                for field, value in (result.get("data") or {}).items():
                    if value in (None, ""):
                        continue
                    try:
                        metadata = {"source_node_id": node_id, "source": "ai_extraction", "sensitive": str(field).lower() in {"cpf", "cnpj", "email", "e-mail"}}
                        if store_fact(db, session.tenant_id, runtime_input.contact_id, f"{field}: {value}", fact_type=data.get("memory_type", data.get("memoryType", "custom")), importance_score=data.get("memory_importance_score", data.get("memoryImportanceScore", 0.7)), conversation_id=runtime_input.conversation_id, session_id=session.id, source="ai_extraction", metadata=metadata):
                            memory_saved_count += 1
                    except Exception as exc:
                        logger.warning("[AI EXTRACTION NODE] memory_save_failed node_id=%s error=%s", node_id, type(exc).__name__)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_extraction", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="success", input_text=input_text, output_text=json.dumps({"fields": found_fields}, ensure_ascii=False), confidence=result.get("confidence"), fallback_used=False, metadata={"found_fields": found_fields, "missing_fields": result.get("missing_fields") or [], "auto_memory_saved_count": memory_saved_count})
            self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "ai_extraction_completed", "fields": list((result.get("data") or {}).keys()), "confidence": result.get("confidence"), "auto_memory_saved_count": memory_saved_count})
            actions = ()
            if data.get("send_debug_message") is True or data.get("sendDebugMessage") is True:
                actions = (SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=f"IA Extração: {json.dumps(result.get('data'), ensure_ascii=False)}", metadata={"node_id": node_id, "intent": "ai_extraction_debug"}),)
            return NodeExecutionResult(actions=actions, next_node_id=self._default_next_or_terminal(db, snapshot=snapshot, session=session, node_id=node_id), status="continue")
        except Exception as exc:
            logger.warning("[AI STRUCTURED NODE] extraction failed node_id=%s error=%s", node_id, exc)
            record_ai_execution(db, tenant_id=session.tenant_id, conversation_id=runtime_input.conversation_id, session_id=session.id, flow_id=get_flow_id(db, snapshot, session), flow_version_id=session.flow_version_id, node_id=node_id, node_type="ai_extraction", provider=ai_config.get("provider"), model=ai_config.get("model"), started_at=ai_started_at, status="error", fallback_used=True, metadata={"error": "ai_extraction_failed"})
            return self._fail(db, snapshot=snapshot, session=session, node_id=node_id, error="ai_extraction_failed")


def _normalize_ai_rag_after_answer_behavior(data: dict[str, Any]) -> AiRagAfterAnswerBehavior:
    raw = data.get(
        "after_agent_behavior",
        data.get("afterAgentBehavior", data.get("after_answer_behavior", data.get("afterAnswerBehavior", AiRagAfterAnswerBehavior.END_FLOW))),
    )
    try:
        return AiRagAfterAnswerBehavior(str(raw).strip())
    except ValueError:
        logger.info("[AI RAG NODE] default_used field=after_answer_behavior default=%s invalid_value=%r", AiRagAfterAnswerBehavior.END_FLOW, raw)
        return AiRagAfterAnswerBehavior.END_FLOW


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
            "action": ActionNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "media": MediaNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "cta_url": CtaUrlNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "cta_link": CtaUrlNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_rag": AiRagNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_response": AiResponseNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_agent": AiAgentNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_supervisor": AiSupervisorNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_classification": AiClassificationNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_extraction": AiExtractionNodeExecutor(
                event_store=event_store, transition_resolver=transition_resolver
            ),
            "ai_summary": AiSummaryNodeExecutor(
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
