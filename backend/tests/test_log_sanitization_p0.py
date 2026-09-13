from __future__ import annotations

import logging
from types import SimpleNamespace

from app.flow_v2.template_renderer import FlowRenderContext, render_template
from app.services.message_origin_trace import log_message_origin_trace
from app.services.message_service import normalize_meta_message
from app.utils.log_sanitizer import outbound_payload_context, provider_response_context


SENTINELS = (
    "SECRET_TOKEN_VALUE",
    "5516999999999",
    "PATIENT_NAME_SENTINEL",
    "MESSAGE_CONTENT_SENTINEL",
)


def _assert_no_sentinels(log_text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in log_text


def test_send_worker_log_context_excludes_payload_content(caplog) -> None:
    payload = {
        "tenant_id": "tenant-1",
        "job_id": "job-1",
        "node_id": "node-1",
        "node_type": "message",
        "message_type": "text",
        "phone": "5516999999999",
        "text": "MESSAGE_CONTENT_SENTINEL PATIENT_NAME_SENTINEL",
        "token": "SECRET_TOKEN_VALUE",
    }
    response = {"status": "accepted", "messages": [{"id": "MESSAGE_CONTENT_SENTINEL"}], "contacts": [{"wa_id": "5516999999999"}]}

    with caplog.at_level(logging.INFO):
        logging.getLogger("app.workers.send_worker").info("[V2 SEND WORKER] payload_json=%s", outbound_payload_context(payload))
        logging.getLogger("app.workers.send_worker").info("[WORKER AFTER META] %s", provider_response_context(response))

    _assert_no_sentinels(caplog.text)
    assert "tenant-1" in caplog.text
    assert "job-1" in caplog.text
    assert "node-1" in caplog.text
    assert "text_len" in caplog.text
    assert "message_id_hash" in caplog.text


def test_message_origin_trace_logs_length_without_text_or_normal_stack(caplog) -> None:
    with caplog.at_level(logging.INFO):
        log_message_origin_trace(
            executor="executor-1",
            flow_id="flow-1",
            node_id="node-1",
            node_type="message",
            message="MESSAGE_CONTENT_SENTINEL",
            context={"phone": "5516999999999", "token": "SECRET_TOKEN_VALUE"},
        )

    _assert_no_sentinels(caplog.text)
    assert "message_len=24" in caplog.text
    assert "source_function=test_message_origin_trace_logs_length_without_text_or_normal_stack" in caplog.text
    assert "stack_included=False" in caplog.text


def test_normalize_meta_message_logs_shape_not_raw_customer_data(caplog) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "token": "SECRET_TOKEN_VALUE",
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "5516999999999", "profile": {"name": "PATIENT_NAME_SENTINEL"}}],
            "messages": [{"id": "wamid-1", "from": "5516999999999", "type": "text", "text": {"body": "MESSAGE_CONTENT_SENTINEL"}}],
        }}]}],
    }

    with caplog.at_level(logging.INFO):
        normalized = normalize_meta_message(payload)

    assert normalized[0]["text"] == "MESSAGE_CONTENT_SENTINEL"
    _assert_no_sentinels(caplog.text)
    assert "entry_count" in caplog.text
    assert "message_count" in caplog.text
    assert "has_text" in caplog.text


def test_session_template_logs_metadata_only(caplog) -> None:
    session = SimpleNamespace(
        id="session-1",
        variables={"patient_name": "PATIENT_NAME_SENTINEL", "token": "SECRET_TOKEN_VALUE"},
        context={"phone": "5516999999999", "last_message": "MESSAGE_CONTENT_SENTINEL"},
    )
    context = FlowRenderContext(tenant_id="tenant-1", session=session, node_id="node-1")

    with caplog.at_level(logging.INFO):
        rendered = render_template("Olá {{patient_name}}", context)

    assert rendered == "Olá PATIENT_NAME_SENTINEL"
    _assert_no_sentinels(caplog.text)
    assert "session_id=session-1" in caplog.text
    assert "node_id=node-1" in caplog.text
    assert "variable_names=['patient_name', 'token']" in caplog.text
    assert "variable_count=2" in caplog.text
    assert "render_success=True" in caplog.text
