from __future__ import annotations

from typing import Any

from app.models.flow_session import set_current_node_id


def _log_session_node(phase: str, session: Any, executed_node_id: Any = None, next_node_id: Any = None, reason: str = "") -> None:
    context = getattr(session, "context", None)
    flow_current_node_id = context.get("flow_current_node_id") if isinstance(context, dict) else None
    print(
        f"[SESSION NODE {phase}] "
        f"session_id={getattr(session, 'id', None)} "
        f"current_node_id={getattr(session, 'current_node_id', None)} "
        f"flow_current_node_id={flow_current_node_id} "
        f"node_id_executado={executed_node_id} "
        f"next_node_id={next_node_id} "
        f"status={getattr(session, 'status', None)} "
        f"reason={reason}"
    )


class FlowEngine:
    def get_start_node(self, flow: dict[str, Any]) -> dict[str, Any] | None:
        nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
        if not isinstance(nodes, list) or not nodes:
            return None

        for node in nodes:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if data.get("isStart") is True:
                return node

        return None

    def get_next_node(self, flow: dict[str, Any], current_node_id: str) -> dict[str, Any] | None:
        nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
        edges = flow.get("edges", []) if isinstance(flow, dict) else []
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None

        node_map = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            if str(edge.get("source") or "") == str(current_node_id):
                target_id = str(edge.get("target") or "")
                return node_map.get(target_id)
        return None

    def process_node(self, node: dict[str, Any], session: Any) -> list[dict[str, str]]:
        node_type = str(node.get("type") or "").lower()
        data = node.get("data") if isinstance(node.get("data"), dict) else {}

        if node_type == "message":
            text = str(data.get("text") or data.get("message") or "")
            if text:
                return [{"type": "text", "content": text}]
            return []

        if node_type == "input":
            session.status = "waiting_input"
            context = session.context if isinstance(session.context, dict) else {}
            context["waiting_input"] = True
            context["input_key"] = str(data.get("key") or "last_input")
            session.context = context
            return []

        return []

    def run_flow(self, flow: dict[str, Any], session: Any) -> dict[str, Any]:
        nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
        if not isinstance(nodes, list) or not nodes:
            return {"messages": [], "next_node": None, "finished": True}

        node_map = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}
        current_node = node_map.get(str(session.current_node_id or "")) if session.current_node_id else self.get_start_node(flow)

        print("FLOW START")
        print("CURRENT NODE:", session.current_node_id or (current_node or {}).get("id"))
        print("USER:", session.user_identifier)

        messages: list[dict[str, str]] = []
        finished = False
        steps = 0

        while current_node and steps < 20:
            current_node_id = str(current_node.get("id") or "")
            _log_session_node("BEFORE", session, executed_node_id=current_node_id, next_node_id=current_node_id, reason="run_flow_execute_node")
            set_current_node_id(session, current_node_id, "legacy_flow_engine_current_node")
            _log_session_node("AFTER", session, executed_node_id=current_node_id, next_node_id=current_node_id, reason="run_flow_execute_node")
            messages.extend(self.process_node(current_node, session))

            if getattr(session, "status", "running") == "waiting_input":
                return {"messages": messages, "next_node": session.current_node_id, "finished": False}

            next_node = self.get_next_node(flow, current_node_id)
            if next_node is None:
                finished = True
                _log_session_node("BEFORE", session, executed_node_id=current_node_id, next_node_id=None, reason="run_flow_no_next_node")
                set_current_node_id(session, None, "legacy_flow_engine_clear_current_node")
                _log_session_node("AFTER", session, executed_node_id=current_node_id, next_node_id=None, reason="run_flow_no_next_node")
                break

            current_node = next_node
            next_node_id = str(current_node.get("id") or "")
            _log_session_node("BEFORE", session, executed_node_id=current_node_id, next_node_id=next_node_id, reason="run_flow_advance")
            set_current_node_id(session, next_node_id, "legacy_flow_engine_next_node")
            _log_session_node("AFTER", session, executed_node_id=current_node_id, next_node_id=next_node_id, reason="run_flow_advance")
            steps += 1

        return {"messages": messages, "next_node": session.current_node_id, "finished": finished}


from app.core.database import SessionLocal
from app.models.flow import Flow
from app.models.flow_session import FlowSession
from app.services.flow_engine_service import get_flow_for_builder


def get_start_node(flow):
    if not flow or "nodes" not in flow:
        return None

    for node in flow["nodes"]:
        if node.get("data", {}).get("isStart") is True:
            return node

    return None


def get_node_by_id(flow, node_id):
    nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
    for node in nodes:
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return None


def process_node(node, session):
    if not node:
        return {
            "messages": [
                {"type": "text", "content": "Erro: node inválido"},
            ]
        }

    node_type = node.get("type")
    data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}

    if node_type == "message":
        text = data.get("text", "")
        return {
            "messages": [
                {"type": "text", "content": text},
            ]
        }

    return {
        "messages": [
            {"type": "text", "content": "Tipo de node não suportado"},
        ]
    }


def run_flow_from_message(user_id: str, text: str):
    db = SessionLocal()
    try:
        default_tenant_id = None
        active_flow = (
            db.query(Flow)
            .filter(Flow.is_active.is_(True))
            .order_by(Flow.updated_at.desc())
            .first()
        )
        if active_flow is None:
            return {"messages": []}

        default_tenant_id = active_flow.tenant_id

        session = (
            db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == default_tenant_id,
                FlowSession.user_identifier == user_id,
            )
            .first()
        )

        if session is None:
            session = FlowSession(
                tenant_id=default_tenant_id,
                user_identifier=user_id,
                conversation_id=user_id,
                flow_id=active_flow.id,
                current_node_id=None,
                status="running",
                context={},
                variables={},
            )
            db.add(session)
            db.commit()
            db.refresh(session)

        flow_data = get_flow_for_builder(db=db, tenant_id=default_tenant_id, flow_id=str(session.flow_id))
        if not isinstance(flow_data, dict):
            return {"messages": []}

        if not session.current_node_id:
            nodes = flow_data.get("nodes", []) if isinstance(flow_data.get("nodes"), list) else []
            start_node = next(
                (n for n in nodes if isinstance(n, dict) and n.get("data", {}).get("isStart") == True),
                None,
            )
            if not start_node:
                print("ERRO: nenhum start node encontrado")
                return {
                    "messages": [
                        {"type": "text", "content": "Erro: fluxo sem início"},
                    ]
                }

            print("[FORCE START]:", start_node["id"])
            _log_session_node("BEFORE", session, executed_node_id=start_node["id"], next_node_id=start_node["id"], reason="force_start")
            set_current_node_id(session, start_node["id"], "legacy_flow_engine_start_node")
            _log_session_node("AFTER", session, executed_node_id=start_node["id"], next_node_id=start_node["id"], reason="force_start")
            db.add(session)
            db.commit()
            _log_session_node("PERSIST", session, executed_node_id=start_node["id"], next_node_id=start_node["id"], reason="force_start")
            return {
                "messages": [
                    {
                        "type": "text",
                        "content": str(start_node.get("data", {}).get("content") or ""),
                    }
                ]
            }

        context = session.context if isinstance(session.context, dict) else {}
        if context.get("waiting_input"):
            input_key = str(context.get("input_key") or "last_input")
            variables = session.variables if isinstance(session.variables, dict) else {}
            variables[input_key] = text
            session.variables = variables
            context["waiting_input"] = False
            context["input_key"] = None
            session.context = context
            session.status = "running"

            current_node = str(session.current_node_id or "")
            edges = flow_data.get("edges", []) if isinstance(flow_data.get("edges"), list) else []
            for edge in edges:
                if isinstance(edge, dict) and str(edge.get("source") or "") == current_node:
                    target_node_id = str(edge.get("target") or "") or None
                    _log_session_node("BEFORE", session, executed_node_id=current_node, next_node_id=target_node_id, reason="waiting_input_advance")
                    set_current_node_id(session, target_node_id, "legacy_flow_engine_choice_target")
                    _log_session_node("AFTER", session, executed_node_id=current_node, next_node_id=target_node_id, reason="waiting_input_advance")
                    break

        node = get_node_by_id(flow_data, session.current_node_id)
        if not node:
            print("[ERRO] node não encontrado")
            return {
                "messages": [
                    {"type": "text", "content": "Erro: node não encontrado"},
                ]
            }
        print("[FLOW] current_node:", session.current_node_id)
        print("[FLOW] executando node:", node)
        preview_result = process_node(node, session)
        print("[FLOW] result:", preview_result)

        engine = FlowEngine()
        result = engine.run_flow(flow_data, session)
        if (not result or "messages" not in result) and preview_result:
            result = preview_result

        if result.get("finished"):
            session.status = "finished"

        db.add(session)
        db.commit()
        _log_session_node("PERSIST", session, executed_node_id=getattr(session, "current_node_id", None), next_node_id=getattr(session, "current_node_id", None), reason="run_flow_from_message_commit")

        if not result or "messages" not in result:
            return {
                "messages": [
                    {"type": "text", "content": "Erro ao processar fluxo"},
                ]
            }

        return {"messages": result.get("messages", [])}
    finally:
        db.close()
