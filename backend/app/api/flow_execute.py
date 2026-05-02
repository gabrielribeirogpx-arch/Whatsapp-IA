from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.tenant import get_current_tenant_id
from app.database import get_db
from app.models.flow import Flow
from app.models.flow_session import FlowSession
from app.services.flow_engine import FlowEngine
from app.services.flow_engine_service import get_flow_for_builder

router = APIRouter(tags=["flow-execution"])

SIMULATION_SESSIONS: dict[str, dict[str, Any]] = {}


class FlowExecutePayload(BaseModel):
    user_id: str
    message: str = ""


class FlowSimulatePayload(BaseModel):
    session_id: str
    message: str = ""


def _normalize_text(value: str | None) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(ch for ch in text if not unicodedata.combining(ch))
    lowered = without_accents.lower().strip()
    return re.sub(r"\s+", " ", lowered)


def _pick_condition_route(edges: list[dict[str, Any]], input_text: str, raw_condition: str) -> tuple[bool, str, str | None]:
    normalized_input = _normalize_text(input_text)
    keywords = [_normalize_text(k) for k in raw_condition.split(",") if _normalize_text(k)]
    matched = any(kw and (kw in normalized_input or (len(normalized_input) >= 2 and normalized_input in kw)) for kw in keywords)
    selected_edge = "true" if matched else "false"
    candidate = next((e for e in edges if str((e.get("sourceHandle") or (e.get("data") or {}).get("sourceHandle") or "")).lower() == selected_edge), None)
    return matched, selected_edge, (str(candidate.get("target")) if isinstance(candidate, dict) and candidate.get("target") else None)


@router.post("/flows/{flow_id}/simulate")
def simulate_flow(flow_id: str, payload: FlowSimulatePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant não informado")

    flow_data = get_flow_for_builder(db=db, tenant_id=tenant_id, flow_id=flow_id)
    if not isinstance(flow_data, dict):
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    key = f"{tenant_id}:{flow_id}:{payload.session_id}"
    state = SIMULATION_SESSIONS.get(key) or {"current_node_id": None}
    nodes = flow_data.get("nodes", []) if isinstance(flow_data.get("nodes"), list) else []
    edges = flow_data.get("edges", []) if isinstance(flow_data.get("edges"), list) else []
    node_map = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id")}

    current_id = state.get("current_node_id")
    if not current_id:
        start = next((n for n in nodes if isinstance(n, dict) and isinstance(n.get("data"), dict) and n["data"].get("isStart") is True), None)
        current_id = str(start.get("id")) if isinstance(start, dict) and start.get("id") else None

    if not current_id:
        raise HTTPException(status_code=400, detail="Flow sem nó inicial")

    current_node = node_map.get(str(current_id))
    current_node_id = str(current_id)
    print(f"[SIMULATOR INPUT] {payload.message}")
    print(f"[SIMULATOR CURRENT NODE] {current_node_id}")

    selected_edge = ""
    matched = False
    next_node_id: str | None = None
    if isinstance(current_node, dict) and str(current_node.get("type") or "").lower() == "condition":
        raw_condition = str((current_node.get("data") or {}).get("condition") or (current_node.get("data") or {}).get("content") or "")
        outgoing = [e for e in edges if isinstance(e, dict) and str(e.get("source") or "") == current_node_id]
        matched, selected_edge, next_node_id = _pick_condition_route(outgoing, payload.message, raw_condition)
        print(f"[SIMULATOR CONDITION MATCH] {matched}")
        print(f"[SIMULATOR EDGE SELECTED] {selected_edge}")
        if next_node_id:
            current_node = node_map.get(next_node_id)
            current_node_id = next_node_id
    else:
        next_edge = next((e for e in edges if isinstance(e, dict) and str(e.get("source") or "") == current_node_id), None)
        next_node_id = str(next_edge.get("target")) if isinstance(next_edge, dict) and next_edge.get("target") else None

    reply = ""
    if isinstance(current_node, dict):
        data = current_node.get("data") if isinstance(current_node.get("data"), dict) else {}
        reply = str(data.get("text") or data.get("content") or data.get("message") or "")

    SIMULATION_SESSIONS[key] = {"current_node_id": current_node_id, "updated_at": str(uuid.uuid4())}
    print(f"[SIMULATOR RESPONSE] {reply}")
    return {
        "reply": reply,
        "current_node_id": current_node_id,
        "next_node_id": next_node_id,
        "matched": matched,
        "selected_edge": selected_edge,
    }


@router.post("/flow/execute")
def execute_flow(payload: FlowExecutePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant não informado")

    session = (
        db.query(FlowSession)
        .filter(
            FlowSession.tenant_id == tenant_id,
            FlowSession.user_identifier == payload.user_id,
        )
        .first()
    )

    if session is None:
        active_flow = (
            db.query(Flow)
            .filter(Flow.tenant_id == tenant_id, Flow.is_active.is_(True))
            .order_by(Flow.updated_at.desc())
            .first()
        )
        if active_flow is None:
            raise HTTPException(status_code=404, detail="Nenhum flow ativo para este tenant")

        session = FlowSession(
            tenant_id=tenant_id,
            user_identifier=payload.user_id,
            flow_id=active_flow.id,
            current_node_id=None,
            status="running",
            context={},
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    flow_data = get_flow_for_builder(db=db, tenant_id=tenant_id, flow_id=str(session.flow_id))
    if not isinstance(flow_data, dict):
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    context = session.context if isinstance(session.context, dict) else {}
    if context.get("waiting_input"):
        input_key = str(context.get("input_key") or "last_input")
        variables = session.variables if isinstance(session.variables, dict) else {}
        variables[input_key] = payload.message
        session.variables = variables
        context["waiting_input"] = False
        context["input_key"] = None
        session.context = context
        session.status = "running"

        current_node = str(session.current_node_id or "")
        edges = flow_data.get("edges", []) if isinstance(flow_data.get("edges"), list) else []
        for edge in edges:
            if isinstance(edge, dict) and str(edge.get("source") or "") == current_node:
                session.current_node_id = str(edge.get("target") or "") or None
                break

    engine = FlowEngine()
    result = engine.run_flow(flow_data, session)

    if result.get("finished"):
        session.status = "finished"

    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "messages": result.get("messages", []),
        "next_node": result.get("next_node"),
        "finished": bool(result.get("finished", False)),
    }
