from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.executors._legacy import _agent_system_message_intent, _normalize_ai_dispatcher_intent
from app.flow_v2.node_executors import AiAgentNodeExecutor
from app.flow_v2.snapshot import FlowV2Snapshot
from app.flow_v2.transition_resolver import TransitionResolver


class EventStore:
    def __init__(self):
        self.events = []

    def append(self, *args, **kwargs):
        self.events.append(kwargs)


def _run_dispatcher(message_text: str, transitions: tuple[dict, ...] | None = None):
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    events = EventStore()
    node = {
        "id": "dispatcher",
        "type": "ai_agent",
        "data": {
            "ai_system_internal_type": "ai_dispatcher",
            "after_agent_behavior": "continue_to_next",
        },
    }
    nodes = (
        node,
        {"id": "greeting", "type": "ai_agent", "data": {}},
        {"id": "calendar", "type": "ai_agent", "data": {}},
        {"id": "fallback", "type": "ai_agent", "data": {}},
    )
    edges = (
        {"id": "e-greeting", "source": "dispatcher", "target": "greeting", "sourceHandle": "greeting"},
        {"id": "e-calendar", "source": "dispatcher", "target": "calendar", "sourceHandle": "calendar_create"},
        {"id": "e-unknown", "source": "dispatcher", "target": "fallback", "sourceHandle": "unknown"},
    )
    snapshot = FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash="hash",
        nodes=nodes,
        edges=edges,
        transitions=transitions if transitions is not None else (),
        start_node_id="dispatcher",
    )
    session = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, flow_version_id=flow_version_id, context={})
    runtime_input = RuntimeInput(
        tenant_id=tenant_id,
        flow_version_id=flow_version_id,
        external_user_id="whatsapp:+55",
        message_text=message_text,
        metadata={"message_id": "m1"},
    )
    result = AiAgentNodeExecutor(event_store=events, transition_resolver=TransitionResolver(events)).execute(
        object(), snapshot=snapshot, session=session, node=node, runtime_input=runtime_input
    )
    return result, events


def test_ai_agent_internal_dispatcher_routes_greeting_by_intent_source_handle():
    result, events = _run_dispatcher("oi")

    assert result.status == "continue"
    assert result.intent == "greeting"
    assert result.next_source_handle == "greeting"
    assert result.next_node_id == "greeting"
    assert any(event["payload"]["analytics_event"] == "AI_DISPATCHER_INTENT_DETECTED" for event in events.events)


def test_ai_agent_internal_dispatcher_routes_calendar_create_by_intent_source_handle():
    result, _events = _run_dispatcher("Agende uma reunião amanhã às 16:30")

    assert result.status == "continue"
    assert result.intent == "calendar_create"
    assert result.next_source_handle == "calendar_create"
    assert result.next_node_id == "calendar"


def test_ai_agent_internal_dispatcher_falls_back_to_unknown_transition():
    transitions = (
        {"id": "e-unknown", "source_node_id": "dispatcher", "target_node_id": "fallback", "source_handle": "unknown"},
    )
    result, _events = _run_dispatcher("oi", transitions=transitions)

    assert result.intent == "greeting"
    assert result.next_source_handle == "unknown"
    assert result.next_node_id == "fallback"



def test_agent_system_message_intent_acceptance_examples():
    assert _agent_system_message_intent("oi") == "greeting"
    assert _agent_system_message_intent("Marque uma Call Online com Gustavo amanhã às 13:30") == "calendar_create"
    assert _agent_system_message_intent("Olá, agende uma reunião amanhã às 15h") == "calendar_create"
    assert _agent_system_message_intent("Tenho horário livre amanhã?") == "calendar_list"
    assert _agent_system_message_intent("Cancelar reunião de amanhã") == "calendar_delete"
    assert _agent_system_message_intent("texto desconhecido") == "unknown"


def test_normalize_ai_dispatcher_intent_calendar_aliases():
    assert _normalize_ai_dispatcher_intent("calendar") == "calendar_create"
    assert _normalize_ai_dispatcher_intent("schedule") == "calendar_create"
    assert _normalize_ai_dispatcher_intent("create_event") == "calendar_create"
    assert _normalize_ai_dispatcher_intent("create_calendar_event") == "calendar_create"
    assert _normalize_ai_dispatcher_intent("agendamento") == "calendar_create"
    assert _normalize_ai_dispatcher_intent("agendar") == "calendar_create"

def test_normalize_ai_dispatcher_intent_accepts_supported_llm_shapes():
    assert _normalize_ai_dispatcher_intent("greeting") == "greeting"
    assert _normalize_ai_dispatcher_intent({"intent": "calendar_list"}) == "calendar_list"
    assert _normalize_ai_dispatcher_intent({"tool": "responder", "arguments": {"intent": "calendar_delete"}}) == "calendar_delete"
    assert _normalize_ai_dispatcher_intent({"tool": "responder", "arguments": {"text": "sales_lead"}}) == "sales_lead"
    assert _normalize_ai_dispatcher_intent({"tool": "responder", "arguments": {"mensagem": "rag_question"}}) == "rag_question"
    assert _normalize_ai_dispatcher_intent("not-a-real-intent") == "unknown"
