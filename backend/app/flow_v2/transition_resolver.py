from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.flow_v2.contracts import FlowV2EventType
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.snapshot import FlowV2Snapshot


class FlowV2TransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransitionResolution:
    target_node_id: str
    edge: dict[str, Any]


class TransitionResolver:
    """Resolves explicit Runtime V2 edges without V1 fallback heuristics."""

    def __init__(self, event_store: FlowV2EventStore | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()

    def resolve(
        self,
        db,
        *,
        snapshot: FlowV2Snapshot,
        session: Any,
        source_node_id: str,
        source_handle: str | None = None,
    ) -> TransitionResolution:
        matches = self._matches(snapshot=snapshot, source_node_id=source_node_id, source_handle=source_handle)
        if not matches:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=source_node_id,
                payload={"source_handle": source_handle},
            )
            raise FlowV2TransitionError("Runtime V2 transition not found")
        if len(matches) > 1:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_AMBIGUOUS,
                node_id=source_node_id,
                payload={"source_handle": source_handle, "match_count": len(matches)},
            )
            raise FlowV2TransitionError("Runtime V2 transition is ambiguous")

        edge = matches[0]
        target = edge.get("target") or edge.get("to") or edge.get("target_node_id")
        if not target or str(target) not in snapshot.node_by_id:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=source_node_id,
                payload={"source_handle": source_handle, "target_node_id": str(target) if target else None},
            )
            raise FlowV2TransitionError("Runtime V2 transition target is invalid")
        return TransitionResolution(target_node_id=str(target), edge=dict(edge))

    @staticmethod
    def _matches(
        *, snapshot: FlowV2Snapshot, source_node_id: str, source_handle: str | None = None
    ) -> list[dict[str, Any]]:
        outgoing = [
            edge
            for edge in snapshot.edges
            if str(edge.get("source") or edge.get("from") or edge.get("source_node_id")) == source_node_id
        ]
        if source_handle is None:
            return [edge for edge in outgoing if edge.get("sourceHandle") in (None, "") and edge.get("source_handle") in (None, "")]
        return [
            edge
            for edge in outgoing
            if str(edge.get("sourceHandle") if edge.get("sourceHandle") is not None else edge.get("source_handle"))
            == source_handle
        ]
