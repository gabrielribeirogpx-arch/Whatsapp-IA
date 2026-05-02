from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.services.flow_engine_service import get_flow_for_builder
from app.services.flow_session_service import FlowSessionService


logger = logging.getLogger(__name__)


def _summarize_reply(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    masked = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    masked = re.sub(r"\+?\d[\d\s().-]{7,}\d", "[phone]", masked)
    masked = re.sub(r"\s+", " ", masked).strip()
    return masked[:120] + ("..." if len(masked) > 120 else "")


def _normalize_text(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    no_accents = "".join(c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn")
    no_punct = re.sub(r"[^\w\s]", " ", no_accents)
    return re.sub(r"\s+", " ", no_punct).strip()


def _node_type(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("type") or data.get("type") or data.get("kind") or "").strip().lower()


def _extract_delay_seconds(node: dict[str, Any] | None) -> int:
    data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
    raw_delay = data.get("seconds") or data.get("delay") or data.get("duration") or data.get("content") or (node.get("content") if isinstance(node, dict) else None)
    try:
        seconds = int(float(str(raw_delay).strip()))
    except Exception:
        seconds = 1
    return max(1, seconds)


async def execute_node_chain_until_reply(
    graph: dict[str, Any],
    start_node_id: str | None,
    user_input: str,
    tenant_id: str | None = None,
    wa_id: str | None = None,
    db: Session | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _result(
        *,
        pending: bool,
        reply: str | None,
        response_node_id: str | None,
        next_node_id: str | None,
    ) -> dict[str, Any]:
        return {
            "pending": pending,
            "reply": reply,
            "response_node_id": response_node_id,
            "next_node_id": next_node_id,
        }

    context = context or {}
    nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
    edges = graph.get("edges", []) if isinstance(graph, dict) else []
    node_map = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id") is not None}

    def find_next(source_id: str, preferred_handles: list[str] | None = None) -> str | None:
        outgoing = [e for e in edges if isinstance(e, dict) and str(e.get("source")) == str(source_id)]
        if not outgoing:
            return None
        for handle in preferred_handles or []:
            for edge in outgoing:
                sh = str(edge.get("sourceHandle") or (edge.get("data") or {}).get("sourceHandle") or "").strip().lower()
                if sh == handle:
                    return str(edge.get("target"))
        return str(outgoing[0].get("target"))

    cursor = start_node_id
    normalized_input = _normalize_text(user_input)
    replies: list[str] = []
    response_node_id: str | None = None
    logger.info("[CORE EXECUTOR START] tenant_id=%s wa_id=%s start_node_id=%s context=%s", tenant_id, wa_id, start_node_id, context)
    while cursor:
        node = node_map.get(str(cursor))
        if not node:
            break
        ntype = _node_type(node)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        logger.info("[CORE NODE TYPE] node_id=%s node_type=%s", cursor, ntype)

        if ntype == "message":
            reply = str(data.get("text") or data.get("content") or data.get("label") or "")
            logger.info("[MESSAGE SENT] node_id=%s", cursor)
            logger.info("[CORE REPLY BUILT] node_id=%s reply_summary=%s", cursor, _summarize_reply(reply))
            if reply:
                replies.append(reply)
            response_node_id = str(cursor)
            next_id = find_next(str(cursor), ["default", "", "output"])
            next_node = node_map.get(str(next_id)) if next_id else None
            next_type = _node_type(next_node)
            if next_type in {"delay", "action", "message"}:
                logger.info("[MESSAGE HAS AUTO_CONTINUE] node_id=%s", cursor)
                logger.info("[AUTO_CONTINUE TO] next_node_id=%s next_type=%s", next_id, next_type)
                cursor = next_id
                continue
            return _result(pending=False, reply="\n\n".join(replies) or None, response_node_id=response_node_id, next_node_id=next_id)

        if ntype == "condition":
            if replies:
                logger.info("[AUTO_CONTINUE PAUSED_AT_CONDITION] node_id=%s", cursor)
                return _result(pending=False, reply="\n\n".join(replies) or None, response_node_id=response_node_id, next_node_id=str(cursor))
            raw_condition = str(data.get("condition") or data.get("keywords") or data.get("content") or "")
            keywords = [_normalize_text(p) for p in raw_condition.replace("\n", ",").split(",") if str(p).strip()]
            is_true = any(k and (k in normalized_input or normalized_input in k) for k in keywords)
            cursor = find_next(str(cursor), ["true", "sim"] if is_true else ["false", "nao", "não"])
            continue

        if ntype == "delay":
            logger.info("[DELAY NODE HIT] node_id=%s", cursor)
            seconds = _extract_delay_seconds(node)
            logger.info("[DELAY SECONDS] %s", seconds)
            if seconds <= 5 or context.get("channel") == "simulator":
                await asyncio.sleep(seconds)
            else:
                return _result(
                    pending=True,
                    reply=None,
                    response_node_id=str(cursor),
                    next_node_id=find_next(str(cursor), ["default", "", "output"]),
                )
            cursor = find_next(str(cursor), ["default", "", "output"])
            logger.info("[DELAY CONTINUE TO] next_node_id=%s", cursor)
            continue

        if ntype == "action":
            cursor = find_next(str(cursor), ["default", "", "output"])
            logger.info("[AUTO_CONTINUE TO] next_node_id=%s next_type=unknown", cursor)
            continue

        cursor = find_next(str(cursor))

    return _result(pending=False, reply="\n\n".join(replies) or None, response_node_id=response_node_id, next_node_id=None)


async def execute_until_message_or_end(
    graph: dict[str, Any],
    current_node_id: str | None,
    user_input: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await execute_node_chain_until_reply(
        graph=graph,
        start_node_id=current_node_id,
        user_input=user_input,
        context=context,
    )


class FlowRuntimeService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _get_next_node(
        current_node_id: str,
        edges: list[dict[str, Any]],
        condition: str | None = None,
    ) -> str | None:
        for edge in edges:
            if str(edge.get("source") or "") != current_node_id:
                continue
            if condition:
                if str(edge.get("sourceHandle") or "") == condition:
                    return str(edge.get("target") or "") or None
                continue
            return str(edge.get("target") or "") or None
        return None

    def execute_flow(self, flow_id: str, input_text: str) -> dict[str, Any]:
        """
        Executa um fluxo simples:
        - encontra start node
        - executa nodes sequencialmente
        - suporta message e condition
        """
        flow_data = get_flow_for_builder(self.db, tenant_id=None, flow_id=flow_id)

        nodes = flow_data.get("nodes", []) if isinstance(flow_data, dict) else []
        edges = flow_data.get("edges", []) if isinstance(flow_data, dict) else []
        nodes = nodes if isinstance(nodes, list) else []
        edges = edges if isinstance(edges, list) else []

        if not nodes:
            return {"responses": [], "steps": 0}

        node_map = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}

        start_node = next(
            (
                n
                for n in nodes
                if isinstance(n, dict)
                and (
                    n.get("type") == "start"
                    or bool((n.get("data") if isinstance(n.get("data"), dict) else {}).get("isStart"))
                )
            ),
            None,
        )

        if start_node is None:
            start_node = nodes[0] if isinstance(nodes[0], dict) else None

        current_node = start_node
        responses: list[str] = []
        max_steps = 20
        steps = 0

        input_text_normalized = str(input_text or "")

        while current_node and steps < max_steps:
            node_id = str(current_node.get("id") or "")
            node_type = str(current_node.get("type") or "").lower()
            data = current_node.get("data", {})
            if not isinstance(data, dict):
                data = {}

            if node_type == "message":
                text = data.get("text") or data.get("message") or "..."
                responses.append(str(text))

                next_id = self._get_next_node(node_id, edges)
                current_node = node_map.get(next_id)

            elif node_type == "condition":
                keywords = data.get("keywords", [])
                if not isinstance(keywords, list):
                    keywords = []

                match = any(str(k).lower() in input_text_normalized.lower() for k in keywords)
                branch = "true" if match else "false"

                next_id = self._get_next_node(node_id, edges, branch)
                current_node = node_map.get(next_id)
            else:
                next_id = self._get_next_node(node_id, edges)
                current_node = node_map.get(next_id)

            steps += 1

        return {
            "responses": responses,
            "steps": steps,
        }

    def execute_with_session(self, flow_id: str, conversation_id: str, input_text: str) -> dict[str, Any]:
        session_service = FlowSessionService(self.db)
        try:
            session = session_service.get_or_create_session(flow_id, conversation_id)
        except Exception:
            flow_data = get_flow_for_builder(self.db, tenant_id=None, flow_id=flow_id)
            nodes = flow_data.get("nodes", []) if isinstance(flow_data, dict) else []
            edges = flow_data.get("edges", []) if isinstance(flow_data, dict) else []
            nodes = nodes if isinstance(nodes, list) else []
            edges = edges if isinstance(edges, list) else []
            start_node = next(
                (
                    n
                    for n in nodes
                    if isinstance(n, dict)
                    and (
                        n.get("type") == "start"
                        or bool((n.get("data") if isinstance(n.get("data"), dict) else {}).get("isStart"))
                    )
                ),
                nodes[0] if nodes and isinstance(nodes[0], dict) else None,
            )
            return {
                "responses": [],
                "session_node": str(start_node.get("id")) if isinstance(start_node, dict) else None,
                "status": "fallback_start",
                "steps": 0,
            }

        flow_data = get_flow_for_builder(self.db, tenant_id=None, flow_id=flow_id)

        nodes = flow_data.get("nodes", []) if isinstance(flow_data, dict) else []
        edges = flow_data.get("edges", []) if isinstance(flow_data, dict) else []
        nodes = nodes if isinstance(nodes, list) else []
        edges = edges if isinstance(edges, list) else []

        if not nodes:
            return {
                "responses": [],
                "session_node": session.current_node_id,
                "status": session.status,
                "steps": 0,
            }

        node_map = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}

        if session.current_node_id:
            current_node = node_map.get(str(session.current_node_id))
        else:
            current_node = next(
                (
                    n
                    for n in nodes
                    if isinstance(n, dict)
                    and (
                        n.get("type") == "start"
                        or bool((n.get("data") if isinstance(n.get("data"), dict) else {}).get("isStart"))
                    )
                ),
                nodes[0] if isinstance(nodes[0], dict) else None,
            )

        responses: list[str] = []
        status = session.status or "running"
        max_steps = 20
        steps = 0
        input_text_normalized = str(input_text or "").lower()

        while current_node and steps < max_steps:
            node_id = str(current_node.get("id") or "")
            node_type = str(current_node.get("type") or "").lower()
            data = current_node.get("data", {})
            if not isinstance(data, dict):
                data = {}

            next_id: str | None = None
            status = "running"

            if node_type == "message":
                text = data.get("text") or data.get("message") or ""
                responses.append(str(text))
                next_id = self._get_next_node(node_id, edges)
            elif node_type == "condition":
                keywords = data.get("keywords", [])
                if not isinstance(keywords, list):
                    keywords = []

                match = any(str(k).lower() in input_text_normalized for k in keywords)
                branch = "true" if match else "false"
                next_id = self._get_next_node(node_id, edges, branch)
            elif node_type == "input":
                status = "waiting_input"
                next_id = node_id
            elif node_type == "choice":
                status = "waiting_choice"
                next_id = node_id
            else:
                next_id = self._get_next_node(node_id, edges)

            session_service.update_session(session, next_id, status=status)
            steps += 1

            if status in {"waiting_input", "waiting_choice"}:
                current_node = None
            else:
                current_node = node_map.get(next_id)

        if not current_node and status == "running":
            status = "finished"
            session_service.update_session(session, session.current_node_id, status=status)

        return {
            "responses": responses,
            "session_node": session.current_node_id,
            "status": session.status,
            "steps": steps,
        }
