from uuid import uuid4
from datetime import datetime, timedelta

from app.models.integration_connection import IntegrationConnection
from app.schemas.assistant_configuration import AssistantConfiguratorResponse
from app.services.assistant_configurator_service import AssistantConfiguratorService


def _status(**overrides):
    values = {
        "configured": True,
        "configuration_valid": True,
        "management_mode": "managed",
        "calendar_status": "connected",
        "policy_valid": True,
        "active": False,
        "up_to_date": False,
    }
    values.update(overrides)
    return AssistantConfiguratorService._status_and_notices(**values)


def test_configurator_status_precedence_is_deterministic():
    assert _status(configured=False)[0] == "needs_configuration"
    assert _status(configuration_valid=False)[0] == "configuration_error"
    assert _status(management_mode="customized", calendar_status="inactive")[0] == "customized"
    assert _status(management_mode="unknown")[0] == "configuration_error"
    assert _status(calendar_status="inactive")[0] == "integration_error"
    assert _status(policy_valid=False)[0] == "configuration_error"
    assert _status(active=True, up_to_date=True)[0] == "active"
    assert _status(active=True, up_to_date=False)[0] == "changes_pending"
    assert _status(active=False, up_to_date=False)[0] == "ready_to_activate"


def test_configurator_dto_is_an_explicit_secret_free_contract():
    identifier = uuid4()
    response = AssistantConfiguratorResponse.model_validate({
        "installation_id": identifier,
        "assistant": {
            "type": "appointment", "template_id": "agenda_inteligente",
            "template_version_id": identifier, "flow_id": identifier,
            "flow_name": "Agenda", "status": "active",
        },
        "configuration": {
            "status": "configured", "version": 4, "clinic_name": "Clínica Vida",
            "services": [{"id": "consulta", "label": "Consulta", "duration_minutes": 30}],
            "handoff": {"enabled": True, "reason": "Atendimento humano"},
        },
        "calendar": {"connection_id": identifier, "status": "connected", "provider": "google_calendar",
                     "available_connections": [{"id": identifier, "status": "active", "label": "calendar@example.com"}]},
        "scheduling": {
            "scope": "workspace", "timezone": "America/Sao_Paulo",
            "business_hours": {"monday": [{"start": "08:00", "end": "18:00"}]},
            "slot_interval_minutes": 15, "default_duration_minutes": 30,
        },
        "management": {"mode": "managed", "has_drift": False},
        "activation": {"active": True, "up_to_date": True, "needs_activation": False,
                       "would_replace_active_flow": False},
        "actions": {"can_edit": True, "can_activate": True, "can_open_builder": True},
        "concurrency": {"configuration_version": 4, "managed_flow_version_id": identifier},
        "notices": [],
    })
    serialized = response.model_dump_json()
    for forbidden in ("access_token", "refresh_token", "credentials", "managed_graph_checksum",
                      "nodes", "edges", "asa_patient_ref", "metadata_json"):
        assert forbidden not in serialized


def test_activation_notice_has_a_stable_code():
    status, notices = _status(active=True, up_to_date=False)
    assert status == "changes_pending"
    assert notices == [{"code": "assistant_activation_required", "severity": "warning"}]


class _ConnectionsDb:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, statement):
        params = statement.compile().params
        rows = [row for row in self.rows if row.tenant_id == params["tenant_id_1"]
                and row.provider == params["provider_1"] and row.status == params["status_1"]]
        rows.sort(key=lambda row: (row.created_at, row.id))
        return type("Rows", (), {"all": lambda _self: rows})()


def test_available_connections_are_active_tenant_scoped_and_deterministic():
    tenant_a, tenant_b = uuid4(), uuid4()
    now = datetime.utcnow()
    def connection(tenant_id, status, created_at):
        return IntegrationConnection(id=uuid4(), tenant_id=tenant_id, provider="google_calendar",
                                     auth_type="oauth2", status=status, created_at=created_at,
                                     updated_at=created_at, metadata_json={})
    a2 = connection(tenant_a, "active", now)
    a1 = connection(tenant_a, "active", now - timedelta(days=1))
    a3 = connection(tenant_a, "inactive", now - timedelta(days=2))
    b1 = connection(tenant_b, "active", now - timedelta(days=3))

    result = AssistantConfiguratorService(_ConnectionsDb([a2, a3, b1, a1]))._available_calendar_connections(tenant_a)

    assert [item.id for item in result] == [a1.id, a2.id]
