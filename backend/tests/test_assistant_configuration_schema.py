from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.assistant_configuration import (
    AssistantActivationRequest,
    AssistantConfigurationUpdate,
    AssistantConfigurationV1,
)


def valid_configuration():
    return {
        "schema_version": 1,
        "clinic_name": " Clínica Vida ",
        "services": [{"id": "Consulta Inicial", "label": " Consulta inicial ", "duration_minutes": 30}],
        "google_calendar_connection_id": str(uuid4()),
        "handoff": {"enabled": True, "reason": "Solicitação do paciente"},
    }


def rejected(mutator):
    value = valid_configuration()
    mutator(value)
    with pytest.raises(ValidationError):
        AssistantConfigurationV1.model_validate(value)


def test_configuration_normalizes_customer_text_and_logical_service_id():
    result = AssistantConfigurationV1.model_validate(valid_configuration())
    assert result.clinic_name == "Clínica Vida"
    assert result.services[0].id == "consulta_inicial"
    assert result.services[0].label == "Consulta inicial"


@pytest.mark.parametrize("mutator", [
    lambda x: x.pop("clinic_name"),
    lambda x: x.update(clinic_name="   "),
    lambda x: x.update(clinic_name="<script>alert(1)</script>"),
    lambda x: x.update(services=[]),
    lambda x: x["services"].append(deepcopy(x["services"][0])),
    lambda x: x["services"][0].update(label=" "),
    lambda x: x["services"][0].update(duration_minutes=0),
    lambda x: x["services"][0].update(duration_minutes=481),
    lambda x: x["handoff"].pop("enabled"),
    lambda x: x.update(tenant_id=str(uuid4())),
    lambda x: x.update(credentials={"token": "secret"}),
    lambda x: x["handoff"].update(team_id=str(uuid4())),
])
def test_configuration_rejects_invalid_or_internal_fields(mutator):
    rejected(mutator)


def test_update_envelope_is_strict_and_requires_expected_version():
    with pytest.raises(ValidationError):
        AssistantConfigurationUpdate.model_validate({"configuration": valid_configuration()})
    with pytest.raises(ValidationError):
        AssistantConfigurationUpdate.model_validate({
            "expected_configuration_version": 0,
            "configuration": valid_configuration(),
            "actor": "forged",
        })


def test_activation_envelope_accepts_only_concurrency_and_confirmation_fields():
    version_id = uuid4()
    payload = AssistantActivationRequest.model_validate({
        "expected_configuration_version": 4,
        "expected_managed_flow_version_id": str(version_id),
        "confirm_replace_active_flow": True,
    })
    assert payload.expected_managed_flow_version_id == version_id
    assert payload.confirm_replace_active_flow is True


@pytest.mark.parametrize("field", [
    "flow_id", "flow_version_id", "published_version_id", "nodes", "edges",
    "checksum", "connection_id", "tool_name", "force", "overwrite",
])
def test_activation_envelope_rejects_structural_and_mass_assignment_fields(field):
    body = {
        "expected_configuration_version": 4,
        "expected_managed_flow_version_id": str(uuid4()),
        field: True,
    }
    with pytest.raises(ValidationError):
        AssistantActivationRequest.model_validate(body)


def test_activation_confirmation_is_strict_boolean():
    with pytest.raises(ValidationError):
        AssistantActivationRequest.model_validate({
            "expected_configuration_version": 4,
            "expected_managed_flow_version_id": None,
            "confirm_replace_active_flow": 1,
        })
