from datetime import datetime, timezone
from types import SimpleNamespace
import json
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers import flows
from app.services.flow_export_service import FlowExportError, build_flow_export, safe_export_filename


def _flow(**overrides):
    values = {
        "name": "Clínica Modelo ../",
        "description": "Agendamento",
        "runtime": "v2",
        "status": "draft",
        "is_active": False,
        "version": 7,
        "trigger_type": "default",
        "trigger_value": None,
        "keywords": "agenda",
        "stop_words": None,
        "priority": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_export_preserves_complete_builder_graph_and_draft_contract():
    nodes = [
        {"id": "start", "type": "choice_dynamic", "position": {"x": 12, "y": 34}, "data": {"result_variable": "selected_slot", "appointment_period": "morning", "options": [{"id": "slot-1", "value": "09:00"}]}},
        {"id": "collect", "type": "data_collection", "position": {"x": 300, "y": 34}, "data": {"variable_name": "email", "prompt": "Qual é seu e-mail?"}},
    ]
    edges = [
        {"id": "selected", "source": "start", "target": "collect", "sourceHandle": "selected", "targetHandle": "input"},
        {"id": "empty", "source": "start", "target": "collect", "sourceHandle": "empty"},
        {"id": "success", "source": "collect", "target": "start", "sourceHandle": "success"},
        {"id": "error", "source": "collect", "target": "start", "sourceHandle": "error"},
    ]

    result = build_flow_export(_flow(), nodes=nodes, edges=edges, exported_at=datetime(2026, 9, 26, tzinfo=timezone.utc))

    assert result["format"] == "wazza_flow"
    assert result["schema_version"] == 1
    assert result["exported_at"] == "2026-09-26T00:00:00Z"
    assert result["flow"]["runtime_version"] == "v2"
    assert result["flow"]["status"] == "draft"
    assert result["flow"]["nodes"] == nodes
    assert result["flow"]["edges"] == edges
    assert result["validation"] == {"valid_references": True, "warnings": []}


def test_export_sanitizes_known_credentials_but_keeps_legitimate_token_named_configuration():
    nodes = [{"id": "mcp", "type": "mcp_tool", "data": {
        "connection_id": "tenant-connection-uuid",
        "server_id": "tenant-server-uuid",
        "tool_name": "google_calendar_create_event",
        "max_tokens": 1200,
        "idempotency_key": "{{session.id}}",
        "authorization": "Bearer bad",
        "credentials": {"access_token": "bad", "refresh_token": "worse"},
        "headers": {"Authorization": "Bearer bad", "X-API-Key": "bad", "Accept": "application/json"},
        "nested": [{"password": "bad", "api_key": "bad"}],
    }}]

    result = build_flow_export(_flow(), nodes=nodes, edges=[])
    serialized = str(result).lower()

    for forbidden in ("bearer bad", "worse", "tenant-connection-uuid", "tenant-server-uuid", "'password'", "'api_key'", "'credentials'", "'authorization'"):
        assert forbidden not in serialized
    data = result["flow"]["nodes"][0]["data"]
    assert data["max_tokens"] == 1200
    assert data["idempotency_key"] == "{{session.id}}"
    assert data["headers"]["Accept"] == "application/json"


def test_incomplete_draft_is_exported_with_reference_warning():
    result = build_flow_export(_flow(), nodes=[{"id": "start", "type": "message"}], edges=[{"source": "start", "target": "missing", "sourceHandle": "success"}])
    assert result["flow"]["edges"][0]["sourceHandle"] == "success"
    assert result["validation"]["valid_references"] is False
    assert result["validation"]["warnings"][0]["node_id"] == "missing"


@pytest.mark.parametrize("nodes,edges", [({}, []), ([], {}), (["bad"], [])])
def test_invalid_container_shapes_are_rejected(nodes, edges):
    with pytest.raises(FlowExportError):
        build_flow_export(_flow(), nodes=nodes, edges=edges)


def test_filename_is_safe_and_portable():
    assert safe_export_filename("Clínica Modelo ../") == "clinica-modelo.wazza-flow.json"
    assert safe_export_filename("...") == "fluxo.wazza-flow.json"


class _DB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _request():
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("127.0.0.1", 1)})


def test_endpoint_is_tenant_scoped_audited_and_sets_download_headers(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = _flow(id=uuid.uuid4(), tenant_id=tenant_id)
    db = _DB()
    audited = []
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: flow if kwargs["tenant_id"] == tenant_id else None)
    monkeypatch.setattr(flows, "FlowService", lambda _db: SimpleNamespace(get_flow_with_version=lambda _flow: {
        "nodes": [{"id": "start", "type": "message", "position": {"x": 1, "y": 2}, "data": {"content": "Olá"}}],
        "edges": [], "version": 7,
    }))
    monkeypatch.setattr(flows, "_write_flow_audit_log", lambda *args, **kwargs: audited.append(kwargs) or True)

    response = flows.export_tenant_flow(
        str(flow.id), _request(), str(tenant_id), db, SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="viewer")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="clinica-modelo.wazza-flow.json"'
    assert response.headers["cache-control"] == "private, no-store"
    assert payload["flow"]["nodes"][0]["position"] == {"x": 1, "y": 2}
    assert audited[0]["action"] == "FLOW_EXPORTED"
    assert "nodes" not in audited[0]["metadata"]
    assert db.commits == 1


def test_endpoint_hides_missing_and_cross_tenant_flows(monkeypatch):
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: None)
    with pytest.raises(HTTPException) as exc:
        flows.export_tenant_flow("missing", _request(), str(tenant_id), _DB(), SimpleNamespace(tenant_id=tenant_id, role="member"))
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as cross_tenant:
        flows.export_tenant_flow("secret", _request(), str(tenant_id), _DB(), SimpleNamespace(tenant_id=uuid.uuid4(), role="admin"))
    assert cross_tenant.value.status_code == 404


def test_endpoint_rejects_unknown_role_before_read(monkeypatch):
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: pytest.fail("must fail before database lookup"))
    with pytest.raises(HTTPException) as exc:
        flows.export_tenant_flow("flow", _request(), str(tenant_id), _DB(), SimpleNamespace(tenant_id=tenant_id, role="legacy_unknown"))
    assert exc.value.status_code == 403
