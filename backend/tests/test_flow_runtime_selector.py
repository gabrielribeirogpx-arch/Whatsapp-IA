from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.flow_v2.contracts import FlowV2SessionStatus, RuntimeOutput
from app.flow_v2.runtime_worker import FlowV2WorkerResult
from app.services.flow_runtime_selector import FlowRuntimeSelector, resolve_flow_runtime


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
