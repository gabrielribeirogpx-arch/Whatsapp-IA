from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.flow_v2.contracts import FlowV2EventType
from app.flow_v2.flow_certifier import _executor, _runtime_input


@dataclass(frozen=True)
class ChaosScenarioResult:
    name: str
    passed: bool
    details: str = ""


@dataclass(frozen=True)
class ChaosTestReport:
    status: str
    scenarios: tuple[ChaosScenarioResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


class FlowV2ChaosTestSuite:
    """Deterministic Runtime V2 chaos simulations for idempotency and restart safety."""

    def run(self) -> ChaosTestReport:
        scenarios = (
            self.worker_crash(),
            self.duplicate_webhook(),
            self.duplicate_delay(),
            self.duplicate_choice(),
        )
        return ChaosTestReport(status="PASSED" if all(scenario.passed for scenario in scenarios) else "FAILED", scenarios=scenarios)

    def worker_crash(self) -> ChaosScenarioResult:
        payload = _message_payload()
        executor, snapshot, event_store, session, db = _executor(payload)
        try:
            executor.handle_input(db, _runtime_input(snapshot, metadata={"message_id": "crash-msg"}))
            checkpoint = (session.current_node_id, session.status, session.last_event_index)
            recovered_executor, _snapshot, _recovered_events, recovered_session, recovered_db = _executor(payload)
            recovered_session.id = session.id
            recovered_session.current_node_id = session.current_node_id
            recovered_session.status = session.status
            recovered_session.last_event_index = session.last_event_index
            recovered_executor.handle_input(recovered_db, _runtime_input(snapshot, metadata={"message_id": "after-crash"}))
            passed = checkpoint[0] == "middle" and recovered_session.last_event_index > checkpoint[2]
            return ChaosScenarioResult("worker_crash", passed, f"checkpoint={checkpoint}, recovered_index={recovered_session.last_event_index}")
        except Exception as exc:  # noqa: BLE001
            return ChaosScenarioResult("worker_crash", False, str(exc))

    def duplicate_webhook(self) -> ChaosScenarioResult:
        return self._duplicate_signal("duplicate_webhook", _message_payload(), {"message_id": "dup-webhook", "event_type": "webhook"})

    def duplicate_delay(self) -> ChaosScenarioResult:
        return self._duplicate_signal("duplicate_delay", _delay_payload(), {"delay_job_id": "dup-delay", "event_type": "delay"})

    def duplicate_choice(self) -> ChaosScenarioResult:
        return self._duplicate_signal("duplicate_choice", _choice_payload(), {"row_id": "yes", "choice_id": "dup-choice", "event_type": "choice"})

    def _duplicate_signal(self, name: str, payload: dict[str, Any], metadata: dict[str, Any]) -> ChaosScenarioResult:
        try:
            executor, snapshot, event_store, _session, db = _executor(payload)
            first = executor.handle_input(db, _runtime_input(snapshot, metadata=metadata))
            second = executor.handle_input(db, _runtime_input(snapshot, metadata=metadata))
            passed = first.emitted_event_count > 0 and second.emitted_event_count == 0
            events = tuple(event["event_type"] for event in event_store.events)
            return ChaosScenarioResult(name, passed, f"first={first.emitted_event_count}, second={second.emitted_event_count}, events={events}")
        except Exception as exc:  # noqa: BLE001
            return ChaosScenarioResult(name, False, str(exc))


def run_chaos_tests() -> ChaosTestReport:
    return FlowV2ChaosTestSuite().run()


def assert_chaos_tests() -> None:
    report = run_chaos_tests()
    if not report.passed:
        details = "; ".join(f"{scenario.name}: {scenario.details}" for scenario in report.scenarios if not scenario.passed)
        raise AssertionError(f"Flow V2 chaos tests failed: {details}")


def _message_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot_schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "hello"},
            {"id": "middle", "type": "message", "content": "middle"},
            {"id": "done", "type": "message", "content": "done"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "middle"}, {"id": "e2", "source": "middle", "target": "done"}],
    }


def _delay_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot_schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "delay", "seconds": 1}, {"id": "done", "type": "message", "content": "done"}],
        "edges": [{"id": "e1", "source": "start", "target": "done"}],
    }


def _choice_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot_schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "choice", "options": [{"id": "yes", "label": "Yes"}]}, {"id": "done", "type": "message", "content": "done"}],
        "edges": [{"id": "e1", "source": "start", "sourceHandle": "yes", "target": "done"}],
    }
