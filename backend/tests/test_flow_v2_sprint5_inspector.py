from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.flow_v2.inspector.execution_inspector import FlowV2ExecutionInspector
from app.flow_v2.inspector.healthcheck import FlowV2Healthcheck
from app.flow_v2.inspector.recovery import FlowV2RecoveryEngine
from app.flow_v2.inspector.session_replay import FlowV2SessionReplay
from app.flow_v2.inspector.session_timeline import FlowV2SessionTimeline
from app.flow_v2.inspector.snapshot_diff import FlowV2SnapshotDiff
from app.flow_v2.snapshot import canonical_hash


def _event(index, event_type, *, session_id, flow_version_id, node_id=None, payload=None):
    return SimpleNamespace(
        event_index=index,
        event_type=event_type,
        session_id=session_id,
        flow_version_id=flow_version_id,
        node_id=node_id,
        payload=payload or {},
        input_message_id="wamid.1" if event_type == "input.received" else None,
        created_at=datetime(2026, 6, 3, 12, index, 0),
    )


def _events():
    session_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    events = [
        _event(1, "session.started", session_id=session_id, flow_version_id=flow_version_id, payload={"start_node_id": "start", "snapshot_hash": "h"}),
        _event(2, "input.received", session_id=session_id, flow_version_id=flow_version_id, node_id="start", payload={"text": "oi"}),
        _event(3, "NODE_ENTERED", session_id=session_id, flow_version_id=flow_version_id, node_id="start"),
        _event(4, "MESSAGE_SENT", session_id=session_id, flow_version_id=flow_version_id, node_id="start", payload={"node_id": "start", "message": "Olá"}),
        _event(5, "NODE_EXECUTED", session_id=session_id, flow_version_id=flow_version_id, node_id="start", payload={"node_type": "message", "status": "continue"}),
        _event(6, "NODE_COMPLETED", session_id=session_id, flow_version_id=flow_version_id, node_id="start"),
        _event(7, "TRANSITION_SELECTED", session_id=session_id, flow_version_id=flow_version_id, node_id="start", payload={"target_node_id": "next"}),
        _event(8, "session.waiting", session_id=session_id, flow_version_id=flow_version_id, node_id="next"),
    ]
    return session_id, flow_version_id, events


def test_replay_completo_reconstroi_sessao_usando_apenas_eventos() -> None:
    session_id, flow_version_id, events = _events()

    replay = FlowV2SessionReplay().from_events(list(reversed(events)), session_id=session_id)

    assert replay.session_id == session_id
    assert replay.flow_version_id == flow_version_id
    assert replay.current_node_id == "next"
    assert replay.status == "waiting"
    assert replay.last_event["event_type"] == "session.waiting"
    assert replay.last_action["event_type"] == "MESSAGE_SENT"
    assert replay.messages_sent == ({"node_id": "start", "message": "Olá"},)
    assert replay.visited_node_ids == ("start",)


def test_timeline_completa_e_inspector_expoem_ultimo_evento_e_ultima_acao() -> None:
    _, flow_version_id, events = _events()

    timeline = FlowV2SessionTimeline().from_events(list(reversed(events)))
    inspection = FlowV2ExecutionInspector().inspect_events(events)

    assert [entry.event_index for entry in timeline] == list(range(1, 9))
    assert timeline[1].input_message_id == "wamid.1"
    assert inspection.flow_version_id == flow_version_id
    assert inspection.current_node_id == "next"
    assert inspection.status == "waiting"
    assert inspection.last_event["event_index"] == 8
    assert inspection.last_action["payload"] == {"node_id": "start", "message": "Olá"}


def test_snapshot_diff_lista_nodes_edges_e_mensagens_alteradas() -> None:
    before = {
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá"},
            {"id": "removed", "type": "message", "content": "Saiu"},
        ],
        "edges": [{"id": "e_removed", "source": "start", "target": "removed"}],
    }
    after = {
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá atualizado"},
            {"id": "added", "type": "message", "content": "Entrou"},
        ],
        "edges": [{"id": "e_added", "source": "start", "target": "added"}],
    }

    diff = FlowV2SnapshotDiff().diff_snapshots(before, after)

    assert diff.nodes_added == ("added",)
    assert diff.nodes_removed == ("removed",)
    assert diff.edges_added == ("e_added",)
    assert diff.edges_removed == ("e_removed",)
    assert [change.as_dict() for change in diff.messages_changed] == [
        {"node_id": "start", "before": "Olá", "after": "Olá atualizado"}
    ]


def test_healthcheck_detecta_sessoes_orfas_snapshots_invalidos_hash_inconsistente_e_jobs_expirados() -> None:
    now = datetime(2026, 6, 3, 12, 0, 0)
    session_with_event = uuid.uuid4()
    orphan_session = uuid.uuid4()
    valid_snapshot = {"schema_version": 1, "start_node_id": "start", "nodes": [], "edges": []}
    valid_hash = canonical_hash(valid_snapshot)
    invalid_version = uuid.uuid4()
    inconsistent_version = uuid.uuid4()
    expired_job = uuid.uuid4()

    report = FlowV2Healthcheck().check_collections(
        sessions=[SimpleNamespace(id=session_with_event), SimpleNamespace(id=orphan_session)],
        events=[SimpleNamespace(session_id=session_with_event)],
        versions=[
            SimpleNamespace(id=uuid.uuid4(), snapshot=valid_snapshot, v2_snapshot_hash=valid_hash),
            SimpleNamespace(id=invalid_version, snapshot={"nodes": []}, v2_snapshot_hash="bad"),
            SimpleNamespace(id=inconsistent_version, snapshot=valid_snapshot, v2_snapshot_hash="bad"),
        ],
        jobs=[
            SimpleNamespace(id=expired_job, run_at=now - timedelta(hours=2)),
            SimpleNamespace(id=uuid.uuid4(), run_at=now - timedelta(minutes=10)),
        ],
        now=now,
        expired_job_grace=timedelta(hours=1),
    )

    assert report.ok is False
    assert report.orphan_session_ids == (orphan_session,)
    assert report.invalid_snapshot_version_ids == (invalid_version,)
    assert report.inconsistent_hash_version_ids == (inconsistent_version,)
    assert report.expired_job_ids == (expired_job,)


def test_recovery_reconstroi_ponteiro_sem_depender_do_estado_atual() -> None:
    session_id, flow_version_id, events = _events()

    recovered = FlowV2RecoveryEngine().from_events(events, session_id=session_id)

    assert recovered.session_id == session_id
    assert recovered.flow_version_id == flow_version_id
    assert recovered.current_node_id == "next"
    assert recovered.status == "waiting"
    assert recovered.last_event_index == 8
    assert recovered.state["event_count"] == 8
    assert recovered.state["messages_sent"] == [{"node_id": "start", "message": "Olá"}]
