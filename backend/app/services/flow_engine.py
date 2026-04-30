from __future__ import annotations

from typing import Any


class FlowEngine:
    def get_start_node(self, flow: dict[str, Any]) -> dict[str, Any] | None:
        nodes = flow.get("nodes", []) if isinstance(flow, dict) else []
        if not isinstance(nodes, list) or not nodes:
            return None

        for node in nodes:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if node.get("type") == "start" or bool(data.get("isStart")):
                return node

        return nodes[0] if isinstance(nodes[0], dict) else None

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
            session.current_node_id = current_node_id
            messages.extend(self.process_node(current_node, session))

            if getattr(session, "status", "running") == "waiting_input":
                return {"messages": messages, "next_node": session.current_node_id, "finished": False}

            next_node = self.get_next_node(flow, current_node_id)
            if next_node is None:
                finished = True
                session.current_node_id = None
                break

            current_node = next_node
            session.current_node_id = str(current_node.get("id") or "")
            steps += 1

        return {"messages": messages, "next_node": session.current_node_id, "finished": finished}
