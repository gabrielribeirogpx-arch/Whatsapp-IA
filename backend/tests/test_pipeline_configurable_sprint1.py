from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from pydantic import ValidationError

from app.schemas.settings import SettingsUpdateIn
from app.routers import leads as leads_router
from app.services.pipeline_service import (
    ensure_pipeline_stages,
    get_default_pipeline_stage_names,
    normalize_workspace_profile,
    reorder_pipeline_stages,
)


class _FakeDB:
    def __init__(self, existing_stages=None):
        self.flushes = 0
        self.commits = 0
        self.added = []
        self.refreshed = []
        self.existing_stages = existing_stages or []

    def execute(self, _statement):
        return _FakeExecuteResult(self.existing_stages)

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        self.refreshed.append(item)


class _FakeExecuteResult:
    def __init__(self, stages):
        self.stages = stages

    def scalars(self):
        return _FakeScalars(self.stages)


class _FakeScalars:
    def __init__(self, stages):
        self.stages = stages

    def all(self):
        return self.stages


def test_workspace_profile_defaults_are_supported_and_safe() -> None:
    assert normalize_workspace_profile("private_sales") == "private_sales"
    assert normalize_workspace_profile("government") == "government"
    assert normalize_workspace_profile("unknown") == "private_sales"
    assert get_default_pipeline_stage_names("private_sales")[:3] == ["Novo", "Qualificado", "Proposta"]
    assert get_default_pipeline_stage_names("government")[:3] == ["Entrada", "Triagem", "Em atendimento"]


def test_settings_schema_rejects_profiles_outside_sprint_scope() -> None:
    assert SettingsUpdateIn(workspace_profile="government").workspace_profile == "government"
    try:
        SettingsUpdateIn(workspace_profile="departments")
    except ValidationError as exc:
        assert "workspace_profile" in str(exc)
    else:
        raise AssertionError("workspace_profile should only allow Sprint 1 profiles")


def test_reorder_pipeline_stages_uses_temporary_positions_before_final_order() -> None:
    db = _FakeDB()
    stages = [
        SimpleNamespace(id="b", position=1),
        SimpleNamespace(id="a", position=0),
        SimpleNamespace(id="c", position=2),
    ]

    reordered = reorder_pipeline_stages(db, stages)

    assert [stage.id for stage in reordered] == ["b", "a", "c"]
    assert [stage.position for stage in reordered] == [0, 1, 2]
    assert db.flushes == 2


def test_list_pipeline_stage_creation_can_be_committed_before_returning_ids() -> None:
    db = _FakeDB()

    stages = ensure_pipeline_stages(db, "tenant-id", commit_created=True)

    assert [stage.name for stage in stages] == get_default_pipeline_stage_names("private_sales")
    assert db.flushes == 1
    assert db.commits == 1
    assert db.added == stages
    assert db.refreshed == stages


def test_update_pipeline_stage_uses_returned_stage_id_and_persists_name(monkeypatch) -> None:
    stage = SimpleNamespace(id=uuid.uuid4(), name="Recebido", position=0)
    tenant = SimpleNamespace(id=uuid.uuid4())
    db = _FakeDB(existing_stages=[stage])

    def fake_get_stage_or_404(received_db, received_tenant_id, received_stage_id):
        assert received_db is db
        assert received_tenant_id == tenant.id
        assert received_stage_id == stage.id
        return stage

    monkeypatch.setattr(leads_router, "_get_stage_or_404", fake_get_stage_or_404)

    response = leads_router.update_pipeline_stage(
        stage.id,
        leads_router.PipelineStageUpdate(name="Recebido atualizado"),
        tenant=tenant,
        db=db,
    )

    assert response.id == stage.id
    assert response.name == "Recebido atualizado"
    assert db.commits == 1
    assert db.refreshed == [stage]
