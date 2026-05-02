from __future__ import annotations

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


class FlowExecutePayload(BaseModel):
    user_id: str
    message: str = ""


# NOTE:
# A rota canônica de simulação do builder é:
#   POST /api/flows/{flow_id}/simulate
# implementada em app.routers.flows::simulate_tenant_flow.
# Este módulo mantém apenas execução conversacional (/flow/execute) para runtime.


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
