from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.flow_v2.contracts import FlowV2SessionStatus, RuntimeOutput
from app.flow_v2.runtime_worker import FlowV2WorkerResult
from app.services import flow_runtime_selector
from app.services.flow_runtime_selector import (
    FlowRuntimeSelector,
    resolve_flow_runtime,
    resolve_runtime_flow_for_conversation,
)


class _FakeWorker:
    def __init__(self):
        self.calls = []

    def process(self, db, input_event):
        self.calls.append({"db": db, "input_event": input_event})
        return FlowV2WorkerResult(
            runtime_output=RuntimeOutput(
                session_id=uuid.uuid4(),
                status=FlowV2SessionStatus.WAITING,
                current_node_id="start",
                emitted_event_count=3,
            ),
            actions=(),
            deliveries=(),
        )


def test_missing_or_unknown_runtime_stays_on_v1() -> None:
    assert resolve_flow_runtime(None) == "v1"
    assert resolve_flow_runtime(SimpleNamespace(runtime=None)) == "v1"
    assert resolve_flow_runtime(SimpleNamespace(runtime="legacy")) == "v1"


def test_v2_runtime_dispatches_to_flow_v2_worker() -> None:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    worker = _FakeWorker()
    flow = SimpleNamespace(id=uuid.uuid4(), runtime="v2", published_version_id=flow_version_id)
    conversation = SimpleNamespace(id=conversation_id)

    result = FlowRuntimeSelector(runtime_worker=worker).dispatch(
        db=object(),
        flow=flow,
        tenant_id=tenant_id,
        phone="5511999999999",
        message_text="oi",
        conversation=conversation,
        contact_id=contact_id,
        input_message_id="wamid-1",
        metadata={"source": "test"},
    )

    assert result.runtime == "v2"
    assert result.processed_by_v2 is True
    assert result.should_run_v1 is False
    assert len(worker.calls) == 1
    input_event = worker.calls[0]["input_event"]
    assert input_event.tenant_id == tenant_id
    assert input_event.flow_version_id == flow_version_id
    assert input_event.external_user_id == "5511999999999"
    assert input_event.conversation_id == conversation_id
    assert input_event.contact_id == contact_id
    assert input_event.input_message_id == "wamid-1"
    assert input_event.metadata["flow_runtime_selector"] == "flow.runtime"



def test_enqueue_whatsapp_text_prefers_structured_tenant_id(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    provider_id = str(uuid.uuid4())
    enqueued = []

    monkeypatch.setattr(flow_runtime_selector, "enqueue_send_message", lambda payload: enqueued.append(payload) or "job-1")

    result = flow_runtime_selector._enqueue_whatsapp_text(
        recipient_id="5511999999999",
        text="Olá! Como posso te ajudar?",
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        metadata={"provider_id": provider_id, "node_id": "start"},
    )

    payload = enqueued[0]
    assert result["tenant_id"] == str(tenant_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["tenant_id"] != ""
    assert payload["provider_id"] == provider_id
    assert payload["session_id"] == str(session_id)
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["contact_id"] == str(contact_id)
    assert payload["node_id"] == "start"
    assert payload["metadata"] == {"provider_id": provider_id, "node_id": "start"}

def test_v1_runtime_does_not_call_flow_v2_worker() -> None:
    worker = _FakeWorker()
    flow = SimpleNamespace(id=uuid.uuid4(), runtime="v1", published_version_id=uuid.uuid4())

    result = FlowRuntimeSelector(runtime_worker=worker).dispatch(
        db=object(),
        flow=flow,
        tenant_id=uuid.uuid4(),
        phone="5511999999999",
        message_text="oi",
    )

    assert result.runtime == "v1"
    assert result.should_run_v1 is True
    assert worker.calls == []


def test_whatsapp_adapter_enqueues_choice_buttons_without_runtime_selector(monkeypatch) -> None:
    from app.flow_v2.actions import SendChoiceButtonsAction
    from app.flow_v2.channel_adapter import WhatsAppAdapter
    from app.services import queue as queue_service

    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    enqueued = []

    monkeypatch.setattr(queue_service, "enqueue_send_message", lambda payload: enqueued.append(payload) or "job-choice")

    action = SendChoiceButtonsAction(
        tenant_id=tenant_id,
        session_id=session_id,
        external_user_id="5511999999999",
        conversation_id=conversation_id,
        contact_id=contact_id,
        text="Escolha",
        node_id="choice",
        options=({"id": "quero_planos", "label": "Quero planos"},),
        buttons=({"id": "quero_planos", "title": "Quero planos"},),
        metadata={
            "tenant_id": str(tenant_id),
            "flow_id": "flow-1",
            "flow_version_id": "version-1",
            "provider_id": "provider-1",
            "node_id": "choice",
            "node_type": "choice",
        },
    )

    delivery = WhatsAppAdapter(client=object()).dispatch(action)

    payload = enqueued[0]
    assert delivery == {
        "status": "queued",
        "channel": "whatsapp",
        "type": "buttons",
        "recipient_id": "5511999999999",
        "job_id": "job-choice",
        "tenant_id": str(tenant_id),
    }
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["phone"] == "5511999999999"
    assert payload["text"] == "Escolha"
    assert payload["interactive_type"] == "button"
    assert payload["node_id"] == "choice"
    assert payload["node_type"] == "choice"
    assert payload["buttons"] == [{"id": "quero_planos", "title": "Quero planos"}]
    assert payload["options"] == [{"id": "quero_planos", "label": "Quero planos"}]


def test_human_conversation_does_not_dispatch_v2_runtime() -> None:
    tenant_id = uuid.uuid4()
    worker = _FakeWorker()
    flow = SimpleNamespace(id=uuid.uuid4(), runtime="v2", published_version_id=uuid.uuid4())
    conversation = SimpleNamespace(id=uuid.uuid4(), mode="human")

    resolved_flow = resolve_runtime_flow_for_conversation(
        db=object(),
        tenant_id=tenant_id,
        conversation=conversation,
        message_text="oi",
    )
    result = FlowRuntimeSelector(runtime_worker=worker).dispatch(
        db=object(),
        flow=flow,
        tenant_id=tenant_id,
        phone="5511999999999",
        message_text="oi",
        conversation=conversation,
    )

    assert resolved_flow is None
    assert result.runtime == "v2"
    assert result.processed_by_v2 is False
    assert result.automation_skipped is True
    assert result.should_run_v1 is False
    assert worker.calls == []
