from types import SimpleNamespace
from uuid import uuid4

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.executors import AiSystemNodeExecutor
from app.flow_v2.node_executors import EXECUTOR_REGISTRY, NodeExecutorRegistry
from app.flow_v2.snapshot import FlowV2Snapshot
from app.flow_v2.transition_resolver import TransitionResolver


class _EventStore:
    def __init__(self):
        self.events = []

    def append(self, db, *, session, event_type, node_id=None, payload=None, input_message_id=None):
        session.last_event_index += 1
        self.events.append(
            {
                "event_index": session.last_event_index,
                "event_type": event_type,
                "node_id": node_id,
                "payload": payload or {},
                "input_message_id": input_message_id,
            }
        )


def test_ai_system_dispatches_private_runtime_and_waits():
    tenant_id = uuid4()
    flow_version_id = uuid4()
    session_id = uuid4()
    node_id = "ai-system-1"
    snapshot = FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash="h",
        nodes=(
            {
                "id": node_id,
                "type": "ai_system",
                "data": {
                    "system_type": "ai_calendar_agent_system",
                    "internal_nodes": [{"id": "internal-response", "type": "message", "isStart": True, "data": {"text": "Evento encaminhado ao calendário."}}],
                    "internal_edges": [],
                    "tools": ["google_calendar_list_events", "google_calendar_create_event"],
                    "isEnd": True,
                },
            },
        ),
        edges=(),
        start_node_id=node_id,
    )
    event_store = _EventStore()
    executor = AiSystemNodeExecutor(
        event_store=event_store,
        transition_resolver=TransitionResolver(event_store),
    )
    session = SimpleNamespace(id=session_id, tenant_id=tenant_id, flow_version_id=flow_version_id, context={}, current_node_id=node_id, status="running", last_event_index=0)
    runtime_input = RuntimeInput(
        tenant_id=tenant_id,
        flow_version_id=flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
    )

    result = executor.execute(None, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.status == "wait"
    assert result.next_node_id == node_id
    assert len(result.actions) == 1
    assert result.actions[0].text == "Evento encaminhado ao calendário."
    assert result.actions[0].metadata["node_id"] == "internal-response"
    assert session.context["ai_system_internal_runtime"][node_id]["current_node_id"] == "internal-response"
    assert any(event["payload"].get("analytics_event") == "AI_SYSTEM_INTERNAL_NODE_EXECUTED" for event in event_store.events)
    assert any(event["payload"].get("analytics_event") == "AI_SYSTEM_INTERNAL_RESPONSE" for event in event_store.events)
    event_indexes = [event["event_index"] for event in event_store.events]
    assert event_indexes == list(range(1, len(event_indexes) + 1))
    assert session.last_event_index == len(event_store.events)


def test_ai_system_aliases_are_registered_and_normalized():
    event_store = _EventStore()
    registry = NodeExecutorRegistry(
        event_store=event_store,
        transition_resolver=TransitionResolver(event_store),
    )

    for node_type in ("ai_system", "aiSystem", "ai_agent_system", "intelligent_calendar"):
        assert node_type.strip().lower() in EXECUTOR_REGISTRY
        assert isinstance(registry.get(node_type), AiSystemNodeExecutor)


def test_ai_system_dispatcher_routes_partial_consultoria_to_calendar_create():
    from app.flow_v2.executors import _legacy

    details = _legacy._agent_system_message_intent_details("Gostaria de marcar uma consultoria com Gabriel")

    assert details["intent"] == "calendar_create"
    assert details["confidence"] >= 0.88
    assert any("consultoria" in term for term in details["matched_keywords"])



def test_ai_system_dispatcher_routes_pending_datetime_followup_to_calendar_create():
    from app.flow_v2.executors import _legacy

    tenant_id = uuid4()
    snapshot = FlowV2Snapshot(
        flow_version_id=uuid4(),
        tenant_id=tenant_id,
        hash="h",
        nodes=(
            {"id": "dispatcher", "type": "ai_dispatcher", "data": {}},
            {"id": "calendar", "type": "ai_calendar_agent", "data": {}},
            {"id": "fallback", "type": "ai_safe_fallback", "data": {}},
        ),
        edges=(
            {"id": "e-calendar", "source": "dispatcher", "target": "calendar", "sourceHandle": "calendar_create"},
            {"id": "e-unknown", "source": "dispatcher", "target": "fallback", "sourceHandle": "unknown"},
        ),
        start_node_id="dispatcher",
    )
    event_store = _EventStore()
    executor = _legacy.AiDispatcherNodeExecutor(event_store=event_store, transition_resolver=TransitionResolver(event_store))
    session = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        flow_version_id=snapshot.flow_version_id,
        context={"pending_event": {"title": "Consultoria com Gabriel", "missing_fields": ["date", "time"]}},
        current_node_id="dispatcher",
        status="running",
        last_event_index=0,
    )
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=snapshot.flow_version_id, external_user_id="whatsapp:+5511999999999", message_text="amanhã às 20:30")

    result = executor.execute(None, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.intent == "calendar_create"
    assert result.next_source_handle == "calendar_create"
    assert result.next_node_id == "calendar"
