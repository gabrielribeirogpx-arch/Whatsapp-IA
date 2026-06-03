from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.session_manager import FlowV2SessionManager
from app.flow_v2.snapshot import FlowV2Snapshot, FlowV2SnapshotRepository


class FlowV2ExecutionError(RuntimeError):
    pass


class FlowV2Executor:
    """The single Runtime V2 executor.

    It receives a published flow_version_id, loads exactly one immutable snapshot
    from flow_versions, appends events for every transition, and updates only the
    minimal session pointer needed to resume execution.
    """

    def __init__(
        self,
        *,
        snapshot_repository: FlowV2SnapshotRepository | None = None,
        event_store: FlowV2EventStore | None = None,
        session_manager: FlowV2SessionManager | None = None,
    ) -> None:
        self.snapshot_repository = snapshot_repository or FlowV2SnapshotRepository()
        self.event_store = event_store or FlowV2EventStore()
        self.session_manager = session_manager or FlowV2SessionManager(self.event_store)

    def handle_input(self, db: Session, runtime_input: RuntimeInput) -> RuntimeOutput:
        snapshot = self.snapshot_repository.load(
            db,
            tenant_id=runtime_input.tenant_id,
            flow_version_id=runtime_input.flow_version_id,
        )
        session = self.session_manager.get_or_create(db, runtime_input=runtime_input, snapshot=snapshot)
        emitted_before = session.last_event_index

        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.INPUT_RECEIVED,
            payload={"text": runtime_input.message_text, "metadata": runtime_input.metadata},
            node_id=session.current_node_id,
            input_message_id=runtime_input.input_message_id,
        )

        effects = self._execute_current_node(db, snapshot=snapshot, session=session)
        db.flush()
        return RuntimeOutput(
            session_id=session.id,
            status=FlowV2SessionStatus(session.status),
            current_node_id=session.current_node_id,
            effects=tuple(effects),
            emitted_event_count=session.last_event_index - emitted_before,
        )

    def _execute_current_node(self, db: Session, *, snapshot: FlowV2Snapshot, session: Any) -> list[dict[str, Any]]:
        if not session.current_node_id:
            raise FlowV2ExecutionError("Session has no current node")
        node = snapshot.node_by_id.get(session.current_node_id)
        if node is None:
            raise FlowV2ExecutionError("Current node is absent from immutable snapshot")

        node_id = str(node["id"])
        self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_ENTERED, node_id=node_id)

        effects = self._node_effects(node)
        for effect in effects:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.OUTPUT_EMITTED,
                node_id=node_id,
                payload=effect,
            )
        self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id)

        next_node_id = self._next_node_id(snapshot=snapshot, node_id=node_id)
        if next_node_id is None:
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_COMPLETED, node_id=node_id)
            self.session_manager.move_to(db, session=session, node_id=None, status=FlowV2SessionStatus.COMPLETED)
            return effects

        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.TRANSITION_SELECTED,
            node_id=node_id,
            payload={"target_node_id": next_node_id},
        )
        self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=next_node_id)
        self.session_manager.move_to(db, session=session, node_id=next_node_id, status=FlowV2SessionStatus.WAITING)
        return effects

    @staticmethod
    def _node_effects(node: dict[str, Any]) -> list[dict[str, Any]]:
        node_type = str(node.get("type") or node.get("kind") or "message")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        text = node.get("text") or node.get("content") or data.get("text") or data.get("message")
        if node_type in {"message", "text"} and text:
            return [{"type": "send_message", "text": text}]
        return [{"type": "node_executed", "node_type": node_type}]

    @staticmethod
    def _next_node_id(*, snapshot: FlowV2Snapshot, node_id: str) -> str | None:
        outgoing = [edge for edge in snapshot.edges if str(edge.get("source")) == node_id or str(edge.get("from")) == node_id]
        if len(outgoing) > 1:
            raise FlowV2ExecutionError("Runtime V2 does not allow implicit transition selection")
        if not outgoing:
            return None
        target = outgoing[0].get("target") or outgoing[0].get("to")
        if not target:
            raise FlowV2ExecutionError("Transition has no explicit target")
        return str(target)
