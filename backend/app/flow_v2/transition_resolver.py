from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.flow_v2.contracts import FlowV2EventType
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.snapshot import FlowV2Snapshot, build_snapshot_transition_audit, build_transitions_from_edges, is_default_source_handle, normalize_source_handle

logger = logging.getLogger(__name__)


class FlowV2TransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransitionResolution:
    target_node_id: str
    edge: dict[str, Any]


class TransitionResolver:
    """Resolves explicit Runtime V2 transitions without V1 fallback heuristics."""

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
        transitions = self._snapshot_transitions(snapshot)
        matches = self._matches(transitions=transitions, source_node_id=source_node_id, source_handle=source_handle)
        outgoing = [transition for transition in transitions if str(transition.get("source_node_id")) == source_node_id]
        logger.info(
            "event=TRANSITION_RESOLUTION_INPUT source_node_id=%s source_handle=%s outgoing_transitions=%s",
            source_node_id,
            source_handle,
            outgoing,
        )
        logger.info(
            "[V2 TRANSITION RESOLVER] source_node_id=%s source_handle=%s transitions_count=%s matches_count=%s transitions=%s",
            source_node_id,
            source_handle,
            len(transitions),
            len(matches),
            transitions,
        )
        if not matches:
            logger.error(
                "[CHOICE TRANSITION NOT FOUND] source_node_id=%s source_handle=%s transitions_count=%s outgoing_count=%s reason=no_matching_transition",
                source_node_id,
                source_handle,
                len(transitions),
                len(outgoing),
            )
            audit_report = build_snapshot_transition_audit(
                snapshot,
                source_node_id=source_node_id,
                source_handle=source_handle,
            )
            payload = {
                "source_handle": source_handle,
                "source_node_id": source_node_id,
                "start_node_id": snapshot.start_node_id,
                "nodes_count": len(snapshot.nodes),
                "edges_count": len(snapshot.edges),
                "transitions_count": len(transitions),
                "outgoing_transitions": outgoing,
                "available_source_nodes": sorted({str(transition.get("source_node_id")) for transition in transitions}),
                "audit_report": audit_report,
            }
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=source_node_id,
                payload=payload,
            )
            logger.error("[V2 TRANSITION RESOLVER] transition_not_found payload=%s", payload)
            logger.error("[V2 TRANSITIONS] missing_transition_report=%s", audit_report)
            raise FlowV2TransitionError(
                "Runtime V2 transition not found: "
                f"source_node_id={source_node_id} source_handle={source_handle} "
                f"transitions_count={len(transitions)} outgoing_count={len(outgoing)}"
            )
        if len(matches) > 1:
            payload = {"source_handle": source_handle, "match_count": len(matches), "matches": matches}
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_AMBIGUOUS,
                node_id=source_node_id,
                payload=payload,
            )
            logger.error("[V2 TRANSITION RESOLVER] transition_ambiguous payload=%s", payload)
            raise FlowV2TransitionError(
                "Runtime V2 transition is ambiguous: "
                f"source_node_id={source_node_id} source_handle={source_handle} match_count={len(matches)}"
            )

        transition = matches[0]
        target = transition.get("target_node_id") or transition.get("target") or transition.get("to")
        if not target or str(target) not in snapshot.node_by_id:
            logger.error(
                "[CHOICE TRANSITION NOT FOUND] source_node_id=%s source_handle=%s target_node_id=%s reason=invalid_target",
                source_node_id,
                source_handle,
                target,
            )
            payload = {"source_handle": source_handle, "target_node_id": str(target) if target else None, "transition": transition}
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_NOT_FOUND,
                node_id=source_node_id,
                payload=payload,
            )
            logger.error("[V2 TRANSITION RESOLVER] invalid_target payload=%s", payload)
            raise FlowV2TransitionError(
                "Runtime V2 transition target is invalid: "
                f"source_node_id={source_node_id} source_handle={source_handle} target_node_id={target}"
            )
        logger.info(
            "[CHOICE TRANSITION FOUND] source_node_id=%s source_handle=%s target_node_id=%s transition=%s",
            source_node_id,
            source_handle,
            target,
            transition,
        )
        logger.info(
            "event=TRANSITION_RESOLUTION_MATCHED source_node_id=%s source_handle=%s target_node_id=%s transition=%s",
            source_node_id,
            source_handle,
            target,
            transition,
        )
        logger.info(
            "[V2 TRANSITION RESOLVER] selected source_node_id=%s source_handle=%s target_node_id=%s transition=%s",
            source_node_id,
            source_handle,
            target,
            transition,
        )
        return TransitionResolution(target_node_id=str(target), edge=dict(transition))

    @staticmethod
    def _snapshot_transitions(snapshot: FlowV2Snapshot) -> list[dict[str, Any]]:
        if snapshot.transitions:
            return [dict(transition) for transition in snapshot.transitions]
        return build_transitions_from_edges(snapshot.edges)

    @staticmethod
    def _matches(
        *, transitions: list[dict[str, Any]], source_node_id: str, source_handle: str | None = None
    ) -> list[dict[str, Any]]:
        outgoing = [transition for transition in transitions if str(transition.get("source_node_id")) == source_node_id]
        requested_handle = normalize_source_handle(source_handle)
        if requested_handle is None:
            return [transition for transition in outgoing if is_default_source_handle(transition.get("source_handle"))]
        return [
            transition
            for transition in outgoing
            if normalize_source_handle(transition.get("source_handle")) == requested_handle
        ]
