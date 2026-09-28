from types import SimpleNamespace
import logging

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


def test_certification_edge_mismatch_fails_closed_with_sanitized_response_and_log(monkeypatch, caplog):
    db = _Session()
    secret = "patient-token-credential-never-log"
    manifest = {"runtime": "v2", "start_node_id": "source"}
    nodes = [
        {"id": "source", "type": "mcp_tool", "position": {"x": 0, "y": 0},
         "data": {"template_node_key": "calendar.lookup", "content": secret, "isStart": True}},
        {"id": "target", "type": "message", "position": {"x": 1, "y": 1},
         "data": {"template_node_key": "calendar.result", "content": secret}},
    ]
    edges = [{"id": "edge", "source": "source", "target": "target", "sourceHandle": "timeout",
              "data": {"sourceHandle": "timeout", "condition": "timeout"}}]

    def publish(_self, _db, *, tenant_id, flow_id):
        published = FlowV2Publisher().publish(nodes=db.temporary.nodes_json, edges=db.temporary.edges_json)
        changed = next(item for item in published.snapshot["edges"] if item["data"]["condition"] == "timeout")
        changed["data"]["condition"] = "error"
        return SimpleNamespace(snapshot=published.snapshot,
                               version=SimpleNamespace(v2_snapshot_hash=published.v2_snapshot_hash))

    monkeypatch.setattr("app.services.template_certification_service.FlowV2PublishService.publish_draft", publish)
    with caplog.at_level(logging.WARNING, logger="app.services.template_certification_service"):
        result = TemplateCertificationService(db, tenant_id="tenant").certify(
            manifest=manifest, nodes=nodes, edges=edges,
        )

    assert not result.ok
    assert result.stage == "structural_equivalence"
    issue = result.issues[0]
    assert issue["code"] == "template_snapshot_diverged"
    assert issue["expected"] == {"safe_value": "timeout"}
    assert issue["actual"] == {"safe_value": "error"}
    assert issue["source_template_node_key"] == "calendar.lookup"
    assert issue["target_template_node_key"] == "calendar.result"
    assert issue["edge_fingerprint"]
    assert "template_certification_structural_mismatch" in caplog.text
    assert '"data.condition":{"safe_value":"timeout"}' in caplog.text
    assert secret not in str(result.report())
    assert secret not in caplog.text
