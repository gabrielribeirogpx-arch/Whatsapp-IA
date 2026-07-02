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
        self.events.append(
            {
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
    session = SimpleNamespace(id=session_id, tenant_id=tenant_id, flow_version_id=flow_version_id, context={}, current_node_id=node_id, status="running")
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


def test_ai_system_aliases_are_registered_and_normalized():
    event_store = _EventStore()
    registry = NodeExecutorRegistry(
        event_store=event_store,
        transition_resolver=TransitionResolver(event_store),
    )

    for node_type in ("ai_system", "aiSystem", "ai_agent_system", "intelligent_calendar"):
        assert node_type.strip().lower() in EXECUTOR_REGISTRY
        assert isinstance(registry.get(node_type), AiSystemNodeExecutor)
