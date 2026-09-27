from types import SimpleNamespace
import uuid

import pytest

import app.services.official_marketplace_template_service as module
from app.models import (
    Flow,
    MarketplaceInstallation,
    MarketplaceInstallationResource,
)
from app.models.audit_log import AuditLog


def _published_template():
    template = SimpleNamespace(
        id=uuid.uuid4(), slug="clinicas-agenda", name="Clínicas",
        description="Agenda", modality="Sem IA",
    )
    node_id = str(uuid.uuid4())
    version = SimpleNamespace(
        id=uuid.uuid4(), template_id=template.id, template=template,
        version="1.0", status="published", nodes_snapshot=[{
            "id": node_id, "type": "message", "position": {"x": 0, "y": 0},
            "data": {"text": "Olá"},
        }], edges_snapshot=[], manifest={"runtime": "v2", "start_node_id": node_id},
        dependencies={},
    )
    return template, version


class FakeDB:
    def __init__(self, version):
        self.version = version
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_resource = False
        self.gets = {}

    def scalar(self, _statement):
        return self.version

    def add(self, item):
        if self.fail_resource and isinstance(item, MarketplaceInstallationResource):
            raise RuntimeError("resource failed")
        self.added.append(item)

    def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def get(self, model, object_id):
        return self.gets.get((model, object_id))


def _service(db, role="owner", tenant_id=None):
    tenant_id = tenant_id or uuid.uuid4()
    tenant = SimpleNamespace(id=tenant_id)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role=role)
    return module.OfficialMarketplaceTemplateService(db, tenant, user)


def _successful_install(monkeypatch, role="owner"):
    template, version = _published_template()
    db = FakeDB(version)
    service = _service(db, role=role)

    def publish(_self, session, *, tenant_id, flow_id):
        flow = next(item for item in session.added if isinstance(item, Flow))
        flow_version = SimpleNamespace(id=uuid.uuid4(), flow_id=flow.id, tenant_id=tenant_id)
        return SimpleNamespace(
            version=flow_version,
            snapshot={"nodes": flow.nodes_json, "edges": flow.edges_json,
                      "start_node_id": flow.nodes_json[0]["id"]},
        )

    monkeypatch.setattr(module.FlowV2PublishService, "publish_draft", publish)
    result = service.install(template.slug)
    return service, db, template, version, result


def test_official_install_persists_complete_tenant_scoped_provenance(monkeypatch):
    service, db, template, version, result = _successful_install(monkeypatch)
    installation = next(item for item in db.added if isinstance(item, MarketplaceInstallation))
    resource = next(item for item in db.added if isinstance(item, MarketplaceInstallationResource))
    flow = next(item for item in db.added if isinstance(item, Flow))

    assert result["installation_id"] == str(installation.id)
    assert installation.tenant_id == service.tenant.id
    assert installation.installed_by_user_id == service.user.id
    assert installation.template_id == template.slug  # legacy meaning is preserved
    assert installation.template_version == version.version
    assert installation.status == "completed"
    assert resource.installation_id == installation.id
    assert resource.resource_type == "flow"
    assert resource.resource_id == str(flow.id)
    assert flow.tenant_id == service.tenant.id
    assert resource.metadata_json == {
        "ownership": str(installation.id),
        "template_id": str(template.id),
        "template_version_id": str(version.id),
        "generated_flow_version_id": result["flow_version_id"],
    }
    assert db.commits == 1


def test_completed_audit_has_only_correlatable_provenance_ids(monkeypatch):
    _service_, db, template, version, result = _successful_install(monkeypatch)
    audit = next(item for item in db.added if isinstance(item, AuditLog))
    assert audit.action == "template_install_completed"
    assert audit.entity_id == result["installation_id"]
    assert audit.metadata_json == {
        "installation_id": result["installation_id"],
        "template_id": str(template.id),
        "template_version_id": str(version.id),
        "flow_id": result["flow_id"],
        "flow_version_id": result["flow_version_id"],
    }


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_non_privileged_roles_cannot_install(monkeypatch, role):
    template, version = _published_template()
    db = FakeDB(version)
    with pytest.raises(PermissionError, match="official_template_forbidden"):
        _service(db, role=role).install(template.slug)
    assert db.added == []


@pytest.mark.parametrize("failure", ["publish", "resource"])
def test_failure_rolls_back_installation_and_flow(monkeypatch, failure):
    template, version = _published_template()
    db = FakeDB(version)
    service = _service(db)
    if failure == "publish":
        monkeypatch.setattr(module.FlowV2PublishService, "publish_draft", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("flow failed")))
    else:
        db.fail_resource = True

        def publish(_self, session, *, tenant_id, flow_id):
            flow = next(item for item in session.added if isinstance(item, Flow))
            return SimpleNamespace(version=SimpleNamespace(id=uuid.uuid4(), flow_id=flow.id), snapshot={"nodes": flow.nodes_json, "edges": [], "start_node_id": flow.nodes_json[0]["id"]})

        monkeypatch.setattr(module.FlowV2PublishService, "publish_draft", publish)
    with pytest.raises(RuntimeError):
        service.install(template.slug)
    assert db.rollbacks == 1
    assert db.commits == 0


def test_provenance_loader_reconstructs_exact_chain_and_is_tenant_safe(monkeypatch):
    service, db, template, version, result = _successful_install(monkeypatch)
    installation = next(item for item in db.added if isinstance(item, MarketplaceInstallation))
    resource = next(item for item in db.added if isinstance(item, MarketplaceInstallationResource))
    flow = next(item for item in db.added if isinstance(item, Flow))
    flow_version = SimpleNamespace(id=uuid.UUID(result["flow_version_id"]), flow_id=flow.id)
    installation.resources = [resource]
    db.version = installation
    db.gets = {
        (module.MarketplaceTemplate, template.id): template,
        (module.MarketplaceTemplateVersion, version.id): version,
        (Flow, flow.id): flow,
        (module.FlowVersion, flow_version.id): flow_version,
    }
    provenance = service.get_provenance(installation.id)
    assert provenance == {
        "installation": installation, "template": template,
        "template_version": version, "flow": flow,
        "generated_flow_version": flow_version, "legacy_or_unknown": False,
    }

    db.version = None
    with pytest.raises(LookupError, match="installation_not_found"):
        _service(db, tenant_id=uuid.uuid4()).get_provenance(installation.id)


def test_legacy_installation_is_readable_with_unknown_provenance():
    _, version = _published_template()
    legacy = MarketplaceInstallation(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), template_id="legacy",
        template_slug="legacy", template_type="flow", template_version="0.9",
        automation_level="no_ai", variant="Sem IA", status="completed",
        idempotency_key="legacy-key", installed_by_user_id=uuid.uuid4(),
        manifest_snapshot={}, dependency_snapshot={}, customization_state={},
        created_resources={},
    )
    legacy.resources = []
    db = FakeDB(legacy)
    provenance = _service(db, tenant_id=legacy.tenant_id).get_provenance(legacy.id)
    assert provenance["installation"] is legacy
    assert provenance["legacy_or_unknown"] is True
    assert provenance["template_version"] is None
    assert provenance["generated_flow_version"] is None
