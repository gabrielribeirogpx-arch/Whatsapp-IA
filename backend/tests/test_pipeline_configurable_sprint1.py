from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from pydantic import ValidationError

from app.schemas.settings import SettingsUpdateIn
from app.services.pipeline_service import (
    get_default_pipeline_stage_names,
    normalize_workspace_profile,
    reorder_pipeline_stages,
)


class _FakeDB:
    def __init__(self):
        self.flushes = 0

    def flush(self):
        self.flushes += 1


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
