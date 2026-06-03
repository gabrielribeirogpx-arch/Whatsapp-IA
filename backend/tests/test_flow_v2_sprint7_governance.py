from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.flow_v2.architecture_tests import run_architecture_tests
from app.flow_v2.chaos_tests import run_chaos_tests
from app.flow_v2.dependency_firewall import DependencyFirewallError, assert_flow_v2_dependency_firewall, scan_flow_v2_dependencies
from app.flow_v2.flow_certifier import CERTIFIED, FAILED, certify_flow
from app.flow_v2.flow_v1_to_v2_migrator import FlowV1ToV2Migrator
from app.flow_v2.snapshot_audit import FlowV2SnapshotAuditor
from app.flow_v2.snapshot import canonical_hash


@dataclass
class _Version:
    id: str
    snapshot: dict
    v2_snapshot_hash: str | None
    nodes_count: int
    edges_count: int
    graph_hash: str | None = None


@dataclass
class _Step:
    step_key: str
    message: str
    next_step_map: dict[str, str] | None = None


@dataclass
class _Flow:
    nodes_json: list[dict] | None = None
    edges_json: list[dict] | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None
    steps: list[_Step] | None = None


def _valid_snapshot() -> dict:
    return {
        "schema_version": 1,
        "snapshot_schema_version": 1,
        "version": "flow_v2_snapshot_v1",
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "content": "Olá", "isStart": True}, {"id": "next", "type": "message", "content": "Fim"}],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }


def test_dependency_firewall_passes_for_runtime_v2_source() -> None:
    assert scan_flow_v2_dependencies() == ()
    assert_flow_v2_dependency_firewall()


def test_dependency_firewall_fails_build_for_v1_imports(tmp_path) -> None:
    blocked = tmp_path / "blocked.py"
    blocked.write_text("from app.services.flow_engine_service import FlowEngineService\nimport app.workers.delay_worker\n", encoding="utf-8")

    violations = scan_flow_v2_dependencies(tmp_path)

    assert len(violations) == 2
    with pytest.raises(DependencyFirewallError):
        assert_flow_v2_dependency_firewall(tmp_path)


def test_architecture_tests_guarantee_v2_isolated() -> None:
    report = run_architecture_tests()

    assert report.status == "PASSED"
    assert {result.name for result in report.results} == {"dependency_firewall", "supported_node_surface", "snapshot_validator_surface"}


def test_snapshot_audit_validates_hash_schema_and_counts() -> None:
    snapshot = _valid_snapshot()
    snapshot_hash = canonical_hash(snapshot)
    valid = _Version(str(uuid4()), {**snapshot, "hash": snapshot_hash}, snapshot_hash, nodes_count=2, edges_count=1)
    invalid = _Version(str(uuid4()), {**snapshot, "hash": "bad"}, "0" * 64, nodes_count=3, edges_count=9)

    report = FlowV2SnapshotAuditor().audit_versions([valid, invalid])

    assert report.status == "FAILED"
    assert report.checked_versions == 2
    assert {issue.code for issue in report.issues} >= {"HASH_MISMATCH", "EMBEDDED_HASH_MISMATCH", "NODE_COUNT_MISMATCH", "EDGE_COUNT_MISMATCH"}


def test_flow_certifier_returns_certified_for_replay_transitions_choice_delay_condition() -> None:
    report = certify_flow(_valid_snapshot())

    assert report.status == CERTIFIED
    assert [check.name for check in report.checks] == ["replay", "transitions", "choice", "delay", "condition"]
    assert all(check.passed for check in report.checks)


def test_flow_certifier_returns_failed_for_invalid_snapshot() -> None:
    report = certify_flow({"schema_version": 1, "start_node_id": "missing", "nodes": [], "edges": []})

    assert report.status == FAILED
    assert any(not check.passed for check in report.checks)


def test_chaos_tests_simulate_crash_and_duplicate_signals() -> None:
    report = run_chaos_tests()

    assert report.status == "PASSED"
    assert {scenario.name for scenario in report.scenarios} == {"worker_crash", "duplicate_webhook", "duplicate_delay", "duplicate_choice"}
    assert all(scenario.passed for scenario in report.scenarios)


def test_flow_v1_to_v2_migrator_preserves_graph_nodes_edges_and_transitions() -> None:
    flow = _Flow(
        nodes_json=[
            {"id": "start", "type": "message", "content": "Início", "isStart": True},
            {"id": "choice", "type": "choice", "options": [{"id": "yes", "label": "Sim"}, {"id": "no", "label": "Não"}]},
            {"id": "yes", "type": "message", "content": "Sim"},
            {"id": "no", "type": "message", "content": "Não"},
        ],
        edges_json=[
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "yes", "target": "yes"},
            {"id": "e3", "source": "choice", "sourceHandle": "no", "target": "no"},
        ],
    )

    result = FlowV1ToV2Migrator().migrate(flow)

    assert result.nodes_migrated == 4
    assert result.edges_migrated == 3
    assert result.snapshot["snapshot_schema_version"] == 1
    assert result.snapshot["start_node_id"] == "start"
    assert {node["id"] for node in result.snapshot["nodes"]} == {"start", "choice", "yes", "no"}
    assert {(edge["source"], edge.get("sourceHandle"), edge["target"]) for edge in result.snapshot["edges"]} == {
        ("start", None, "choice"),
        ("choice", "yes", "yes"),
        ("choice", "no", "no"),
    }


def test_flow_v1_to_v2_migrator_converts_steps_when_graph_payload_is_absent() -> None:
    flow = _Flow(steps=[_Step("start", "Olá", {"default": "end"}), _Step("end", "Fim")])

    result = FlowV1ToV2Migrator().migrate(flow)

    assert result.snapshot["start_node_id"] == "start"
    assert result.nodes_migrated == 2
    assert result.edges_migrated == 1
    assert result.snapshot["edges"] == [{"id": "edge_start_default", "source": "start", "target": "end"}]
