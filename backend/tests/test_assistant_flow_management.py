from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models import Flow, FlowVersion, MarketplaceInstallation, MarketplaceInstallationFlowManagement, MarketplaceInstallationResource
from app.models.audit_log import AuditLog
from app.schemas.assistant_configuration import AssistantConfigurationResponse, AssistantConfigurationUpdate
from app.services.assistant_flow_management_service import (
    assert_managed_flow_baseline,
    detect_flow_drift,
    establish_official_baseline,
)
from tests.test_assistant_configuration_schema import valid_configuration


class QueueDB:
    def __init__(self, values=()):
        self.values = list(values)
        self.added = []

    def scalar(self, statement):
        assert self.values, str(statement)
        return self.values.pop(0)

    def add(self, item):
        self.added.append(item)


def graph(tenant_id, checksum="a" * 64):
    flow = Flow(id=uuid4(), tenant_id=tenant_id, name="Assistant")
    version = FlowVersion(id=uuid4(), flow_id=flow.id, tenant_id=tenant_id, version=1, graph_checksum=checksum, nodes=[], edges=[])
    flow.current_version_id = version.id
    return flow, version


def installation_for(flow, tenant_id):
    installation = MarketplaceInstallation(
        id=uuid4(), tenant_id=tenant_id, template_id="official", template_slug="agenda_inteligente",
        template_type="official_flow", template_version="1", automation_level="official", variant="Sem IA",
        status="completed", idempotency_key="key", installed_by_user_id=uuid4(),
    )
    resource = MarketplaceInstallationResource(
        installation_id=installation.id, resource_type="flow", resource_id=str(flow.id), resource_name="Assistant",
        creation_status="created", metadata_json={"template_version_id": str(uuid4())},
    )
    installation.resources = [resource]
    return installation


def management(installation, flow, version, checksum=None, mode="managed"):
    row = MarketplaceInstallationFlowManagement(
        installation_id=installation.id, flow_id=flow.id, management_mode=mode,
        managed_flow_version_id=version.id, managed_graph_checksum=checksum or version.graph_checksum,
    )
    installation.flow_management = row
    return row


def test_establish_baseline_requires_same_flow_tenant_current_and_canonical_checksum():
    tenant_id = uuid4()
    flow, version = graph(tenant_id)
    installation = installation_for(flow, tenant_id)
    db = QueueDB()
    row = establish_official_baseline(db, installation=installation, flow=flow, flow_version=version, checksum=version.graph_checksum)
    assert row in db.added
    assert row.managed_flow_version_id == version.id
    assert row.managed_graph_checksum == version.graph_checksum

    other, other_version = graph(tenant_id)
    with pytest.raises(ValueError, match="invalid_managed_flow_baseline"):
        establish_official_baseline(db, installation=installation, flow=flow, flow_version=other_version, checksum=other_version.graph_checksum)
    foreign_flow, foreign_version = graph(uuid4())
    with pytest.raises(ValueError, match="invalid_managed_flow_baseline"):
        establish_official_baseline(db, installation=installation, flow=foreign_flow, flow_version=foreign_version, checksum=foreign_version.graph_checksum)


def test_same_version_and_checksum_is_managed_without_flow_mutation():
    tenant_id = uuid4(); flow, version = graph(tenant_id); installation = installation_for(flow, tenant_id)
    row = management(installation, flow, version)
    before = (flow.current_version_id, flow.published_version_id, flow.is_active, version.nodes, version.edges)
    db = QueueDB([flow, row, version, version])
    state = detect_flow_drift(db, installation=installation, tenant_id=tenant_id)
    assert state.mode == "managed" and state.has_drift is False
    assert (flow.current_version_id, flow.published_version_id, flow.is_active, version.nodes, version.edges) == before
    assert db.added == []


def test_different_id_equal_checksum_advances_baseline_and_remains_managed():
    tenant_id = uuid4(); flow, baseline = graph(tenant_id); installation = installation_for(flow, tenant_id)
    current = FlowVersion(id=uuid4(), flow_id=flow.id, tenant_id=tenant_id, version=2, graph_checksum=baseline.graph_checksum)
    flow.current_version_id = current.id
    row = management(installation, flow, baseline)
    state = detect_flow_drift(db := QueueDB([flow, row, baseline, current]), installation=installation, tenant_id=tenant_id)
    assert state.mode == "managed" and state.managed_flow_version_id == current.id
    assert row.managed_flow_version_id == current.id
    assert not any(isinstance(item, AuditLog) for item in db.added)


def test_real_drift_marks_customized_and_audits_only_first_detection():
    tenant_id = uuid4(); flow, baseline = graph(tenant_id); installation = installation_for(flow, tenant_id)
    current = FlowVersion(id=uuid4(), flow_id=flow.id, tenant_id=tenant_id, version=2, graph_checksum="b" * 64)
    flow.current_version_id = current.id
    row = management(installation, flow, baseline)
    db = QueueDB([flow, row, baseline, current])
    state = detect_flow_drift(db, installation=installation, tenant_id=tenant_id, actor_id=uuid4())
    assert state.mode == "customized" and state.has_drift is True
    audit = next(item for item in db.added if isinstance(item, AuditLog))
    assert audit.action == "assistant_marked_customized"
    assert set(audit.metadata_json) == {"installation_id", "flow_id", "managed_flow_version_id", "current_flow_version_id", "managed_graph_checksum", "current_graph_checksum", "template_version_id"}
    assert "nodes" not in audit.metadata_json and "edges" not in audit.metadata_json

    second = QueueDB([flow, row, baseline, current])
    detect_flow_drift(second, installation=installation, tenant_id=tenant_id)
    assert not any(isinstance(item, AuditLog) for item in second.added)


def test_incompatible_baseline_checksum_fails_closed_and_missing_baseline_is_unknown():
    tenant_id = uuid4(); flow, version = graph(tenant_id); installation = installation_for(flow, tenant_id)
    row = management(installation, flow, version, checksum="f" * 64)
    state = detect_flow_drift(QueueDB([flow, row, version, version]), installation=installation, tenant_id=tenant_id)
    assert state.mode == "inconsistent" and state.has_drift is None

    installation.flow_management = None
    # No generated_flow_version_id: no heuristic initialization.
    state = detect_flow_drift(QueueDB([flow, None]), installation=installation, tenant_id=tenant_id)
    assert state.mode == "unknown" and state.managed_flow_version_id is None


def test_tenant_isolation_and_concurrency_conflict_fail_closed():
    tenant_id = uuid4(); flow, version = graph(tenant_id); installation = installation_for(flow, tenant_id)
    with pytest.raises(HTTPException) as cross_tenant:
        detect_flow_drift(QueueDB(), installation=installation, tenant_id=uuid4())
    assert cross_tenant.value.status_code == 404

    row = management(installation, flow, version)
    with pytest.raises(HTTPException) as conflict:
        assert_managed_flow_baseline(
            QueueDB([flow, row, version, version]), installation=installation,
            tenant_id=tenant_id, expected_managed_flow_version_id=uuid4(),
        )
    assert conflict.value.status_code == 409


def test_management_dto_is_read_only_and_hides_checksum_and_resource_metadata():
    response = AssistantConfigurationResponse.model_validate({
        "installation_id": uuid4(), "status": "needs_configuration", "configuration_version": 0,
        "configuration": None, "updated_at": None, "updated_by": None,
        "management": {"mode": "unknown", "flow_id": None, "managed_flow_version_id": None,
                       "current_flow_version_id": None, "has_drift": None},
    }).model_dump(mode="json")
    assert "managed_graph_checksum" not in response["management"]
    assert "metadata" not in response and "customization_state" not in response

    for forbidden in ("management_mode", "managed_flow_version_id", "managed_graph_checksum", "has_drift"):
        payload = {"expected_configuration_version": 0, "configuration": valid_configuration(), forbidden: "forged"}
        with pytest.raises(ValidationError):
            AssistantConfigurationUpdate.model_validate(payload)
