from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.appointment_duration_service import (
    AppointmentDurationError,
    SOURCE_ASSISTANT_SERVICE,
    SOURCE_TENANT_DEFAULT,
    resolve_effective_appointment_duration,
)


class FakeDB:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def execute(self, _statement):
        self.calls += 1
        return SimpleNamespace(all=lambda: self.rows)


def configuration():
    return {
        "schema_version": 1, "clinic_name": "Clínica",
        "services": [
            {"id": "consulta", "label": "Consulta", "duration_minutes": 30},
            {"id": "avaliacao", "label": "Avaliação", "duration_minutes": 45},
            {"id": "retorno", "label": "Retorno", "duration_minutes": 20},
        ],
        "google_calendar_connection_id": str(uuid4()),
        "handoff": {"enabled": False, "reason": None},
    }


def managed_rows(*, mode="managed", config=None, binding="appointment_type"):
    version = uuid4()
    installation = SimpleNamespace(manifest_snapshot={"assistant_materialization": {
        "schema_version": 1, "service_selection_variable": binding,
    }})
    row = SimpleNamespace(configuration=configuration() if config is None else config)
    management = SimpleNamespace(management_mode=mode, managed_flow_version_id=version)
    return [(installation, row, management, SimpleNamespace())], version


@pytest.mark.parametrize(("service_id", "minutes"), [
    ("consulta", 30), ("avaliacao", 45), ("retorno", 20),
])
def test_resolves_duration_by_stable_service_id_once(service_id, minutes):
    rows, version = managed_rows()
    db = FakeDB(rows)
    result = resolve_effective_appointment_duration(
        db, tenant_id=uuid4(), flow_id=uuid4(), flow_version_id=version,
        runtime_variables={"appointment_type": service_id, "duration_minutes": 480},
        default_duration_minutes=60,
    )
    assert (result.duration_minutes, result.source, result.service_id) == (
        minutes, SOURCE_ASSISTANT_SERVICE, service_id,
    )
    assert db.calls == 1


@pytest.mark.parametrize(("variables", "code"), [
    ({}, "assistant_service_not_selected"),
    ({"appointment_type": "inexistente"}, "assistant_service_not_found"),
    ({"appointment_type": "Avaliação"}, "assistant_service_not_found"),
])
def test_managed_selection_fails_closed_and_never_uses_label(variables, code):
    rows, version = managed_rows()
    with pytest.raises(AppointmentDurationError, match=code):
        resolve_effective_appointment_duration(
            FakeDB(rows), tenant_id=uuid4(), flow_id=uuid4(), flow_version_id=version,
            runtime_variables=variables, default_duration_minutes=60,
        )


def test_legacy_missing_configuration_binding_and_customized_use_default():
    unbound, version = managed_rows(binding=None)
    customized, customized_version = managed_rows(mode="customized")
    cases = [([], version), ([(SimpleNamespace(manifest_snapshot={}), None, None, SimpleNamespace())], version),
             (unbound, version), (customized, customized_version)]
    for rows, flow_version in cases:
        result = resolve_effective_appointment_duration(
            FakeDB(rows), tenant_id=uuid4(), flow_id=uuid4(), flow_version_id=flow_version,
            runtime_variables={"appointment_type": "avaliacao"}, default_duration_minutes=60,
        )
        assert (result.duration_minutes, result.source, result.service_id) == (
            60, SOURCE_TENANT_DEFAULT, None,
        )


def test_ambiguous_provenance_fails_closed():
    rows, version = managed_rows()
    with pytest.raises(AppointmentDurationError, match="assistant_configuration_invalid"):
        resolve_effective_appointment_duration(
            FakeDB(rows + rows), tenant_id=uuid4(), flow_id=uuid4(), flow_version_id=version,
            runtime_variables={"appointment_type": "consulta"}, default_duration_minutes=60,
        )
