from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid

from app.routers.marketplace import catalog


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeDB:
    def __init__(self, values):
        self.values = values

    def scalars(self, _statement):
        return FakeScalars(self.values)


def version(template, label, published_at, capabilities=None):
    return SimpleNamespace(
        id=uuid.uuid4(), template_id=template.id, template=template, version=label,
        status="published", published_at=published_at, created_at=published_at,
        manifest={"capabilities": capabilities or [], "estimated_time": "8 min", "tags": ["agenda"]},
    )


def test_catalog_exposes_one_safe_latest_version_per_official_template():
    template = SimpleNamespace(
        id=uuid.uuid4(), key="clinicas_agenda", slug="clinicas-agenda-autom-tica",
        name="Clinicas - Agenda Automática", description="Agenda clínica", category="Agendamentos",
        segment="Geral", modality="Sem IA",
    )
    now = datetime.utcnow()
    older = version(template, "1.9.0", now)
    latest = version(template, "1.10.0", now - timedelta(days=1), ["appointment_assistant_configuration"])

    result = catalog(FakeDB([older, latest]), SimpleNamespace())
    official = [item for item in result if item["source"] == "official"]

    assert len(official) == 1
    assert official[0]["version_id"] == str(latest.id)
    assert official[0]["name"] == "Clinicas - Agenda Automática"
    assert official[0]["capabilities"] == ["appointment_assistant_configuration"]
    forbidden = {"manifest", "nodes", "edges", "checksum", "credentials", "tokens", "access_token", "refresh_token", "connection_id"}
    assert forbidden.isdisjoint(official[0])


def test_catalog_keeps_legacy_and_official_items_together():
    template = SimpleNamespace(
        id=uuid.uuid4(), key="new_product", slug="new-product", name="Novo produto",
        description=None, category="Operações", segment="Geral", modality="Híbrido",
    )
    result = catalog(FakeDB([version(template, "1.0.0", datetime.utcnow())]), SimpleNamespace())
    assert any(item["source"] == "legacy" for item in result)
    assert any(item["source"] == "official" for item in result)
