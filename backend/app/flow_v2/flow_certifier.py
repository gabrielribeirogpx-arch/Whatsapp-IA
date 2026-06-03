from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.publisher import FlowV2Publisher
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash
from app.flow_v2.transition_resolver import TransitionResolver


CERTIFIED = "CERTIFIED"
FAILED = "FAILED"


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    passed: bool
    details: str = ""


@dataclass(frozen=True)
class CertificationReport:
    status: str
    checks: tuple[CertificationCheck, ...]

    @property
    def certified(self) -> bool:
        return self.status == CERTIFIED


class FlowV2Certifier:
    """Certifies a Runtime V2 snapshot against replay, transitions, choice, delay and condition contracts."""

    def certify(self, snapshot_payload: dict[str, Any]) -> CertificationReport:
        checks = [
            self._check_replay(snapshot_payload),
            self._check_transitions(snapshot_payload),
            self._check_choice(),
            self._check_delay(),
            self._check_condition(),
        ]
        return CertificationReport(status=CERTIFIED if all(check.passed for check in checks) else FAILED, checks=tuple(checks))

    def _check_replay(self, snapshot_payload: dict[str, Any]) -> CertificationCheck:
        try:
            nodes = list(snapshot_payload.get("nodes") or [])
            edges = list(snapshot_payload.get("edges") or [])
            FlowV2Publisher().publish(nodes=nodes, edges=edges)
            if not edges:
                return CertificationCheck("replay", True, "terminal snapshot validated without transitions")
            executor, snapshot, event_store, session, db = _executor(snapshot_payload)
            executor.handle_input(db, _runtime_input(snapshot))
            emitted = tuple(event["event_type"] for event in event_store.events)
            required = {str(FlowV2EventType.SESSION_STARTED), str(FlowV2EventType.INPUT_RECEIVED), str(FlowV2EventType.NODE_ENTERED)}
            return CertificationCheck("replay", required.issubset(set(emitted)), f"events={emitted}")
        except Exception as exc:  # noqa: BLE001 - certification reports errors as FAILED details
            return CertificationCheck("replay", False, str(exc))

    def _check_transitions(self, snapshot_payload: dict[str, Any]) -> CertificationCheck:
        try:
            snapshot = _snapshot(snapshot_payload)
            if not snapshot.edges:
                return CertificationCheck("transitions", True, "terminal snapshot has no transitions")
            first_edge = snapshot.edges[0]
            source = str(first_edge.get("source") or first_edge.get("from") or first_edge.get("source_node_id"))
            handle = first_edge.get("sourceHandle") if first_edge.get("sourceHandle") is not None else first_edge.get("source_handle")
            resolved = TransitionResolver(_MemoryEventStore()).resolve(
                _FakeDB(), snapshot=snapshot, session=_FakeSession(snapshot), source_node_id=source, source_handle=str(handle) if handle not in (None, "") else None
            )
            return CertificationCheck("transitions", bool(resolved.target_node_id), f"target={resolved.target_node_id}")
        except Exception as exc:  # noqa: BLE001
            return CertificationCheck("transitions", False, str(exc))

    def _check_choice(self) -> CertificationCheck:
        return _scenario_check(
            "choice",
            {
                "schema_version": 1,
                "snapshot_schema_version": 1,
                "start_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "choice", "options": [{"id": "yes", "label": "Yes"}]},
                    {"id": "done", "type": "message", "content": "done"},
                ],
                "edges": [{"id": "e1", "source": "start", "sourceHandle": "yes", "target": "done"}],
            },
            {"row_id": "yes", "choice_id": "choice-1", "event_type": "choice"},
            FlowV2EventType.CHOICE_SELECTED,
        )

    def _check_delay(self) -> CertificationCheck:
        return _scenario_check(
            "delay",
            {
                "schema_version": 1,
                "snapshot_schema_version": 1,
                "start_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "delay", "seconds": 1},
                    {"id": "done", "type": "message", "content": "done"},
                ],
                "edges": [{"id": "e1", "source": "start", "target": "done"}],
            },
            {"delay_job_id": "delay-1", "event_type": "delay"},
            FlowV2EventType.DELAY_SCHEDULED,
        )

    def _check_condition(self) -> CertificationCheck:
        return _scenario_check(
            "condition",
            {
                "schema_version": 1,
                "snapshot_schema_version": 1,
                "start_node_id": "start",
                "nodes": [
                    {"id": "start", "type": "condition", "conditions": [{"field": "plan", "operator": "==", "value": "pro"}]},
                    {"id": "ok", "type": "message", "content": "ok"},
                    {"id": "no", "type": "message", "content": "no"},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "sourceHandle": "true", "target": "ok"},
                    {"id": "e2", "source": "start", "sourceHandle": "false", "target": "no"},
                ],
            },
            {"plan": "pro"},
            FlowV2EventType.CONDITION_EVALUATED,
        )


def certify_flow(snapshot_payload: dict[str, Any]) -> CertificationReport:
    return FlowV2Certifier().certify(snapshot_payload)


def _scenario_check(name: str, payload: dict[str, Any], metadata: dict[str, Any], expected_event: FlowV2EventType) -> CertificationCheck:
    try:
        executor, snapshot, event_store, _session, db = _executor(payload)
        executor.handle_input(db, _runtime_input(snapshot, metadata=metadata))
        emitted = tuple(event["event_type"] for event in event_store.events)
        passed = str(expected_event) in emitted
        return CertificationCheck(name, passed, f"events={emitted}")
    except Exception as exc:  # noqa: BLE001
        return CertificationCheck(name, False, str(exc))


def _snapshot(payload: dict[str, Any]) -> FlowV2Snapshot:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    snapshot_hash = payload.get("hash") or canonical_hash({key: value for key, value in payload.items() if key != "hash"})
    return FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash=snapshot_hash,
        nodes=tuple(dict(node) for node in payload.get("nodes") or []),
        edges=tuple(dict(edge) for edge in payload.get("edges") or []),
        start_node_id=str(payload.get("start_node_id") or "start"),
        snapshot_schema_version=int(payload.get("snapshot_schema_version") or payload.get("schema_version") or 1),
    )


def _executor(payload: dict[str, Any]):
    snapshot = _snapshot(payload)
    event_store = _MemoryEventStore()
    session = _FakeSession(snapshot)
    return (
        FlowV2Executor(snapshot_repository=_SnapshotRepo(snapshot), event_store=event_store, session_manager=_SessionManager(session, event_store)),
        snapshot,
        event_store,
        session,
        _FakeDB(),
    )


def _runtime_input(snapshot: FlowV2Snapshot, metadata: dict[str, Any] | None = None) -> RuntimeInput:
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="certifier-user",
        message_text="certify",
        input_message_id=(metadata or {}).get("message_id") or str(uuid.uuid4()),
        metadata=metadata or {},
    )


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, item: Any) -> None:
        self.added.append(item)

    def flush(self) -> None:
        return None


class _FakeSession:
    def __init__(self, snapshot: FlowV2Snapshot) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = snapshot.tenant_id
        self.flow_version_id = snapshot.flow_version_id
        self.current_node_id = snapshot.start_node_id
        self.status = FlowV2SessionStatus.RUNNING
        self.last_event_index = 0


class _SnapshotRepo:
    def __init__(self, snapshot: FlowV2Snapshot) -> None:
        self.snapshot = snapshot

    def load(self, db: Any, *, tenant_id, flow_version_id) -> FlowV2Snapshot:
        return self.snapshot


class _MemoryEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, db: Any, *, session: Any, event_type: FlowV2EventType, payload: dict[str, Any] | None = None, node_id: str | None = None, input_message_id: str | None = None) -> None:
        session.last_event_index += 1
        self.events.append({"event_index": session.last_event_index, "event_type": str(event_type), "payload": payload or {}, "node_id": node_id, "input_message_id": input_message_id})


class _SessionManager:
    def __init__(self, session: _FakeSession, event_store: _MemoryEventStore) -> None:
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db: Any, *, runtime_input: RuntimeInput, snapshot: FlowV2Snapshot) -> _FakeSession:
        if self.session.last_event_index == 0:
            self.event_store.append(db, session=self.session, event_type=FlowV2EventType.SESSION_STARTED, payload={"snapshot_hash": snapshot.hash, "start_node_id": snapshot.start_node_id})
        return self.session

    def move_to(self, db: Any, *, session: Any, node_id: str | None, status: FlowV2SessionStatus) -> None:
        session.current_node_id = node_id
        session.status = str(status)
