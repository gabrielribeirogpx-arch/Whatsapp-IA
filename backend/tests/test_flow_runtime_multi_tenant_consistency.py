from __future__ import annotations

import asyncio
import sys
import types

_stub_flow_engine = types.ModuleType("app.services.flow_engine_service")
_stub_flow_engine.get_flow_for_builder = lambda *args, **kwargs: {}
sys.modules.setdefault("app.services.flow_engine_service", _stub_flow_engine)
_stub_flow_session = types.ModuleType("app.services.flow_session_service")
class _DummyFlowSessionService:  # pragma: no cover
    pass
_stub_flow_session.FlowSessionService = _DummyFlowSessionService
sys.modules.setdefault("app.services.flow_session_service", _stub_flow_session)

from app.services.flow_runtime_service import execute_node_chain_until_reply


FLOW_GRAPH = {
    "nodes": [
        {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá!"}},
        {"id": "condition", "type": "condition", "data": {"condition": "suporte"}},
        {"id": "response_a", "type": "message", "data": {"text": "Encaminhando para o suporte.", "isEnd": True}},
        {"id": "response_b", "type": "message", "data": {"text": "Tudo bem, posso ajudar com mais algo?", "isEnd": True}},
    ],
    "edges": [
        {"source": "start", "target": "condition", "sourceHandle": "default"},
        {"source": "condition", "target": "response_a", "sourceHandle": "true"},
        {"source": "condition", "target": "response_b", "sourceHandle": "false"},
    ],
}


class _RuntimeHarness:
    def __init__(self, tenant_id: str, flow_id: str):
        self.tenant_id = tenant_id
        self.flow_id = flow_id
        self.sessions: dict[str, dict] = {}

    def incoming(self, user_identifier: str, text: str) -> dict:
        session_key = f"{self.tenant_id}:{self.flow_id}:{user_identifier}"
        session = self.sessions.get(session_key)
        start_node_id = "start" if not session or session.get("status") == "finished" else session.get("current_node_id")

        result = asyncio.run(
            execute_node_chain_until_reply(
                graph=FLOW_GRAPH,
                start_node_id=start_node_id,
                user_input=text,
                tenant_id=self.tenant_id,
                wa_id=user_identifier,
            )
        )

        next_node_id = result.get("next_node_id")
        status = "running"
        if result.get("response_node_id") in {"response_a", "response_b"}:
            status = "finished"
            next_node_id = None

        self.sessions[session_key] = {
            "current_node_id": next_node_id,
            "status": status,
        }
        return result



def test_flow_runtime_multi_tenant_consistency():
    print("[FLOW RUNTIME TEST START]")

    try:
        tenant_a = _RuntimeHarness("tenant-A", "flow-template-simple")
        tenant_b = _RuntimeHarness("tenant-B", "flow-template-simple")

        # 1..6 - tenant novo, flow simples, validação de início até condition
        first_a = tenant_a.incoming("5511999990001", "oi")
        assert first_a["events"][0]["text"] == "Olá!"
        assert tenant_a.sessions["tenant-A:flow-template-simple:5511999990001"]["current_node_id"] == "condition"

        # 7..8 - condição true leva ao response A e finaliza
        second_a = tenant_a.incoming("5511999990001", "gostaria de falar com suporte")
        assert second_a["events"][0]["text"] == "Encaminhando para o suporte."
        assert tenant_a.sessions["tenant-A:flow-template-simple:5511999990001"]["status"] == "finished"

        # 9..10 - nova mensagem reinicia flow no start quando sessão anterior finalizada
        third_a = tenant_a.incoming("5511999990001", "oi")
        assert third_a["events"][0]["text"] == "Olá!"
        assert tenant_a.sessions["tenant-A:flow-template-simple:5511999990001"]["current_node_id"] == "condition"

        # 11 - isolamento entre tenants (B não herda flow/session de A)
        first_b = tenant_b.incoming("5511999990001", "oi")
        assert first_b["events"][0]["text"] == "Olá!"
        assert tenant_b.sessions["tenant-B:flow-template-simple:5511999990001"]["current_node_id"] == "condition"

        # tenant B escolhe branch false para validar independência
        second_b = tenant_b.incoming("5511999990001", "quero outra opção")
        assert second_b["events"][0]["text"] == "Tudo bem, posso ajudar com mais algo?"
        assert tenant_b.sessions["tenant-B:flow-template-simple:5511999990001"]["status"] == "finished"

        # Confirma que tenant A permaneceu isolado após ações do tenant B
        assert tenant_a.sessions["tenant-A:flow-template-simple:5511999990001"]["current_node_id"] == "condition"
        assert tenant_a.sessions["tenant-A:flow-template-simple:5511999990001"]["status"] == "running"

        print("[FLOW RUNTIME TEST PASS]")
    except Exception:
        print("[FLOW RUNTIME TEST FAIL]")
        raise
