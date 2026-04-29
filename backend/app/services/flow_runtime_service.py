from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.flow_engine_service import get_flow_for_builder
from app.services.flow_event_service import FlowEventService
from app.services.flow_session_service import FlowSessionService


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
        event_service = FlowEventService(self.db)
        session = session_service.get_or_create_session(flow_id, conversation_id)

        try:
            event_service.log(flow_id, conversation_id, "FLOW_START")

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
                event_service.log(flow_id, conversation_id, "FLOW_STEP", node_id=node_id)
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
                    event_service.log(flow_id, conversation_id, "FLOW_WAIT", node_id=node_id)
                    current_node = None
                else:
                    current_node = node_map.get(next_id)

            if not current_node and status == "running":
                status = "finished"
                session_service.update_session(session, session.current_node_id, status=status)
                event_service.log(flow_id, conversation_id, "FLOW_END")

            return {
                "responses": responses,
                "session_node": session.current_node_id,
                "status": session.status,
                "steps": steps,
            }
        except Exception as exc:
            event_service.log(flow_id, conversation_id, "FLOW_ERROR", data={"error": str(exc)})
            raise
