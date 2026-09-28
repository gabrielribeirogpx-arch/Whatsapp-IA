from types import SimpleNamespace

from app.flow_v2.publisher import FlowV2Publisher
from app.services.template_certification_service import (
    CERTIFICATION_VERSION,
    TemplateCertificationService,
    candidate_checksum,
)


class _Savepoint:
    is_active = True

    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1
        self.is_active = False


class _Session:
    def __init__(self):
        self.savepoint = _Savepoint()
        self.temporary = None

    def begin_nested(self):
        return self.savepoint

    def add(self, value):
        self.temporary = value

    def flush(self):
        return None


def _candidate():
    return ({"runtime": "v2", "start_node_id": "start"}, [
        {"id": "start", "type": "message", "position": {"x": 0, "y": 0},
         "data": {"content": "sensitive message", "isStart": True}},
    ], [])


def test_simple_flow_certifies_through_publisher_and_always_rolls_back(monkeypatch):
    db = _Session()

    def publish(_self, _db, *, tenant_id, flow_id):
        result = FlowV2Publisher().publish(nodes=db.temporary.nodes_json, edges=db.temporary.edges_json)
        return SimpleNamespace(snapshot=result.snapshot,
                               version=SimpleNamespace(v2_snapshot_hash=result.v2_snapshot_hash))

    monkeypatch.setattr("app.services.template_certification_service.FlowV2PublishService.publish_draft", publish)
    manifest, nodes, edges = _candidate()
    result = TemplateCertificationService(db, tenant_id="tenant").certify(
        manifest=manifest, nodes=nodes, edges=edges,
    )
    assert result.ok
    assert result.certification_version == CERTIFICATION_VERSION
    assert result.candidate_checksum == candidate_checksum(manifest, nodes, edges)
    assert db.savepoint.rollbacks == 1


def test_invalid_reference_fails_closed_without_sensitive_diagnostics():
    manifest, nodes, _ = _candidate()
    result = TemplateCertificationService(_Session(), tenant_id="tenant").certify(
        manifest=manifest, nodes=nodes,
        edges=[{"source": "start", "target": "missing", "token": "do-not-leak"}],
    )
    assert not result.ok
    assert result.stage == "static_validation"
    rendered = str(result.issues)
    assert "do-not-leak" not in rendered
    assert "sensitive message" not in rendered


def test_checksum_distinguishes_missing_from_null_false_list_and_object():
    manifest, nodes, edges = _candidate()
    base = candidate_checksum(manifest, nodes, edges)
    for value in (None, False, [], {}):
        changed = [dict(nodes[0], optional=value)]
        assert candidate_checksum(manifest, changed, edges) != base
