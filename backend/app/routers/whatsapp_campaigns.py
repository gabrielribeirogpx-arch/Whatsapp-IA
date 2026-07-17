from datetime import datetime
import re
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, Tenant, WhatsAppCampaign, WhatsAppCampaignRecipient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.services.queue import get_queue
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/whatsapp/campaigns", tags=["whatsapp-campaigns"])


def _extract_template_variables(template: WhatsAppMessageTemplate) -> list[str]:
    text = "\n".join(
        [
            str(getattr(template, "body_text", "") or ""),
            str(getattr(template, "body_preview", "") or ""),
        ]
    )
    return sorted(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", text)), key=lambda item: int(item))


def _serialize_campaign(c: WhatsAppCampaign) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "status": c.status,
        "provider_id": str(c.provider_id),
        "template_id": str(c.template_id),
        "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "total_recipients": c.total_recipients,
        "total_sent": c.total_sent,
        "total_delivered": c.total_delivered,
        "total_read": c.total_read,
        "total_failed": c.total_failed,
        "metadata_json": c.metadata_json or {},
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("")
def list_campaigns(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    rows = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.tenant_id == tenant.id).order_by(WhatsAppCampaign.created_at.desc())).scalars().all()
    return [_serialize_campaign(c) for c in rows]


@router.post("")
def create_campaign(payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    provider_id = payload.get("provider_id")
    template_id = payload.get("template_id")
    name = str(payload.get("name") or "Campanha").strip() or "Campanha"
    requested_status = str(payload.get("status") or "draft").strip().lower()
    scheduled_at = None
    if payload.get("scheduled_at"):
        scheduled_at = datetime.fromisoformat(str(payload.get("scheduled_at")).replace("Z", "+00:00")).replace(tzinfo=None)
        if scheduled_at <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="Agendamento deve estar no futuro")
        requested_status = "scheduled"
    if requested_status not in {"draft", "scheduled"}:
        requested_status = "draft"

    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id, TenantWhatsAppProvider.tenant_id == tenant.id)).scalars().first()
    if not provider or provider.status != "connected":
        raise HTTPException(status_code=400, detail="Provider is not connected/active")
    template = db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.id == template_id, WhatsAppMessageTemplate.tenant_id == tenant.id)).scalars().first()
    if not template or str(template.status or "").lower() != "approved":
        raise HTTPException(status_code=400, detail="Template is not approved")
    duplicate = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.tenant_id == tenant.id, func.lower(WhatsAppCampaign.name) == name.lower(), WhatsAppCampaign.status.in_(["draft", "scheduled", "running", "paused"]))).scalars().first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe campanha ativa ou rascunho com este nome")

    campaign = WhatsAppCampaign(
        tenant_id=tenant.id,
        provider_id=provider_id,
        template_id=template_id,
        name=name,
        status=requested_status,
        scheduled_at=scheduled_at,
        metadata_json=payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {},
        created_by="console",
    )
    db.add(campaign); db.commit(); db.refresh(campaign)
    if campaign.status == "scheduled" and campaign.scheduled_at:
        get_queue("normal").enqueue_at(campaign.scheduled_at, "app.workers.campaign_worker.process_campaign", str(campaign.id), str(tenant.id), job_timeout=600)
    return _serialize_campaign(campaign)

# --- Campaign analytics helpers/endpoints ---
def _parse_dt(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail="Período inválido")


def _analytics_bounds(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    start_dt = _parse_dt(start, now.replace(hour=0, minute=0, second=0, microsecond=0))
    end_dt = _parse_dt(end, now)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Data inicial deve ser anterior à data final")
    if (end_dt - start_dt).days > 370:
        raise HTTPException(status_code=400, detail="Intervalo máximo: 370 dias")
    return start_dt, end_dt


def _campaign_filters(query, tenant_id, start_dt, end_dt, campaign_id=None, template_id=None, provider_id=None, status=None, template_category=None, template_language=None, search=None):
    query = query.join(WhatsAppMessageTemplate, WhatsAppMessageTemplate.id == WhatsAppCampaign.template_id).where(
        WhatsAppCampaign.tenant_id == tenant_id,
        WhatsAppCampaign.created_at >= start_dt,
        WhatsAppCampaign.created_at <= end_dt,
    )
    if campaign_id:
        query = query.where(WhatsAppCampaign.id == campaign_id)
    if template_id:
        query = query.where(WhatsAppCampaign.template_id == template_id)
    if provider_id:
        query = query.where(WhatsAppCampaign.provider_id == provider_id)
    if status:
        query = query.where(WhatsAppCampaign.status == status)
    if template_category:
        query = query.where(WhatsAppMessageTemplate.category == template_category)
    if template_language:
        query = query.where(WhatsAppMessageTemplate.language == template_language)
    if search:
        query = query.where(WhatsAppCampaign.name.ilike(f"%{search}%"))
    return query


def _rate(num, den):
    return None if not den else round((float(num or 0) / float(den)) * 100, 1)


def _campaign_row(c, t):
    duration = None
    if c.started_at and c.completed_at:
        duration = int((c.completed_at - c.started_at).total_seconds())
    return {**_serialize_campaign(c), "template_name": t.name if t else None, "template_category": t.category if t else None, "template_language": t.language if t else None, "delivery_rate": _rate(c.total_delivered, c.total_sent), "read_rate": _rate(c.total_read, c.total_delivered), "failure_rate": _rate(c.total_failed, c.total_recipients), "duration_seconds": duration}


def normalize_campaign_failure(error_code: str | None, error_message: str | None) -> dict:
    text = f"{error_code or ''} {error_message or ''}".lower()
    rules = [
        ("Telefone inválido", ["phone", "telefone", "invalid recipient", "131026"], "Revise a formatação e o código do país dos destinatários."),
        ("Destinatário indisponível", ["unavailable", "not reachable", "131047"], "Tente novamente mais tarde ou remova contatos indisponíveis recorrentes."),
        ("Template inválido", ["template", "132000", "132001"], "Verifique aprovação, idioma e conteúdo do template na Meta."),
        ("Variável ausente ou inválida", ["variable", "parameter", "missing", "failed_missing_variable"], "Complete as variáveis obrigatórias antes do envio."),
        ("Limite da Meta", ["rate", "limit", "throttle"], "Reduza a cadência de envio ou aguarde a liberação do limite."),
        ("Qualidade ou política", ["policy", "quality", "integrity"], "Revise políticas da Meta e qualidade da conta/template."),
        ("Bloqueio do destinatário", ["blocked", "block"], "Não reenvie para destinatários que bloquearam o remetente."),
        ("Erro temporário da Meta", ["temporary", "timeout", "try again", "500", "503"], "Tente reenviar após estabilização da Meta."),
        ("Autenticação/conexão", ["auth", "token", "permission", "401", "403"], "Reconecte o provider e valide permissões do WhatsApp Business."),
    ]
    for category, needles, action in rules:
        if any(n in text for n in needles):
            return {"category": category, "message": category, "recommendation": action}
    return {"category": "Erro desconhecido", "message": "Falha não categorizada", "recommendation": "Analise os códigos técnicos preservados e tente reenviar quando aplicável."}


@router.get("/analytics/summary")
def analytics_summary(start: str | None = None, end: str | None = None, campaign_id: str | None = None, template_id: str | None = None, provider_id: str | None = None, status: str | None = None, template_category: str | None = None, template_language: str | None = None, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    rows = db.execute(_campaign_filters(select(WhatsAppCampaign), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status, template_category, template_language)).scalars().all()
    totals = {"campaigns_created": len(rows), "campaigns_completed": sum(1 for c in rows if c.status == "completed"), "total_recipients": sum(c.total_recipients or 0 for c in rows), "total_sent": sum(c.total_sent or 0 for c in rows), "total_delivered": sum(c.total_delivered or 0 for c in rows), "total_read": sum(c.total_read or 0 for c in rows), "total_failed": sum(c.total_failed or 0 for c in rows)}
    totals.update({"delivery_rate": _rate(totals["total_delivered"], totals["total_sent"]), "read_rate": _rate(totals["total_read"], totals["total_delivered"]), "failure_rate": _rate(totals["total_failed"], totals["total_recipients"]), "timestamp_basis": {"campaigns": "created_at", "events": "sent_at/delivered_at/read_at/failed_at"}})
    return totals


@router.get("/analytics/by-campaign")
def analytics_by_campaign(start: str | None = None, end: str | None = None, campaign_id: str | None = None, template_id: str | None = None, provider_id: str | None = None, status: str | None = None, template_category: str | None = None, template_language: str | None = None, search: str | None = None, sort: str = "recent", page: int = 1, page_size: int = 20, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end); page=max(page,1); page_size=min(max(page_size,1),100)
    base = _campaign_filters(select(WhatsAppCampaign, WhatsAppMessageTemplate), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status, template_category, template_language, search)
    order = {"sent": WhatsAppCampaign.total_sent.desc(), "delivery_rate": (WhatsAppCampaign.total_delivered / func.nullif(WhatsAppCampaign.total_sent, 0)).desc(), "read_rate": (WhatsAppCampaign.total_read / func.nullif(WhatsAppCampaign.total_delivered, 0)).desc(), "failures": WhatsAppCampaign.total_failed.desc()}.get(sort, WhatsAppCampaign.created_at.desc())
    total = db.execute(select(func.count()).select_from(_campaign_filters(select(WhatsAppCampaign), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status, template_category, template_language, search).subquery())).scalar() or 0
    rows = db.execute(base.order_by(order).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [_campaign_row(c, t) for c, t in rows], "page": page, "page_size": page_size, "total": total}



@router.get("/analytics/by-template")
def analytics_by_template(start: str | None = None, end: str | None = None, campaign_id: str | None = None, template_id: str | None = None, provider_id: str | None = None, status: str | None = None, template_category: str | None = None, template_language: str | None = None, sort: str = "used", db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    rows = db.execute(_campaign_filters(select(WhatsAppCampaign, WhatsAppMessageTemplate), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status, template_category, template_language)).all()
    grouped = {}
    for c, t in rows:
        key = str(c.template_id)
        g = grouped.setdefault(key, {"template_id": key, "template_name": t.name if t else key, "category": t.category if t else None, "language": t.language if t else None, "campaigns": 0, "total_recipients": 0, "total_sent": 0, "total_delivered": 0, "total_read": 0, "total_failed": 0})
        g["campaigns"] += 1
        for field in ["total_recipients", "total_sent", "total_delivered", "total_read", "total_failed"]:
            g[field] += int(getattr(c, field) or 0)
    items = list(grouped.values())
    for item in items:
        item["delivery_rate"] = _rate(item["total_delivered"], item["total_sent"]); item["read_rate"] = _rate(item["total_read"], item["total_delivered"])
    key = {"delivery_rate": lambda x: x["delivery_rate"] or -1, "read_rate": lambda x: x["read_rate"] or -1, "failures": lambda x: x["total_failed"]}.get(sort, lambda x: x["campaigns"])
    return sorted(items, key=key, reverse=True)

@router.get("/analytics/timeline")
def analytics_timeline(start: str | None = None, end: str | None = None, campaign_id: str | None = None, template_id: str | None = None, provider_id: str | None = None, status: str | None = None, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    days = (end_dt - start_dt).total_seconds() / 86400
    grain = "hour" if days <= 2 else "day" if days <= 90 else "month"
    campaigns = _campaign_filters(select(WhatsAppCampaign.id), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status).subquery()
    def bucket(col):
        return func.date_trunc(grain, col)
    data = {}
    for label, col in [("sent", WhatsAppCampaignRecipient.sent_at), ("delivered", WhatsAppCampaignRecipient.delivered_at), ("read", WhatsAppCampaignRecipient.read_at), ("failed", WhatsAppCampaignRecipient.failed_at)]:
        for b, count in db.execute(select(bucket(col), func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id.in_(select(campaigns.c.id)), col >= start_dt, col <= end_dt).group_by(bucket(col))).all():
            if b:
                data.setdefault(b.isoformat(), {"bucket": b.isoformat(), "sent": 0, "delivered": 0, "read": 0, "failed": 0})[label] = count
    return {"grain": grain, "items": [data[k] for k in sorted(data)]}

@router.get("/analytics/failures")
def analytics_failures(start: str | None = None, end: str | None = None, campaign_id: str | None = None, template_id: str | None = None, provider_id: str | None = None, status: str | None = None, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    campaigns = _campaign_filters(select(WhatsAppCampaign.id), tenant.id, start_dt, end_dt, campaign_id, template_id, provider_id, status).subquery()
    rows = db.execute(select(WhatsAppCampaignRecipient.status, WhatsAppCampaignRecipient.error_message, func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id.in_(select(campaigns.c.id)), WhatsAppCampaignRecipient.status.in_(["failed", "failed_missing_variable"])).group_by(WhatsAppCampaignRecipient.status, WhatsAppCampaignRecipient.error_message)).all()
    total = sum(count for _, _, count in rows) or 0; grouped = {}
    for code, message, count in rows:
        norm = normalize_campaign_failure(code, message); g = grouped.setdefault(norm["category"], {**norm, "count": 0, "percent": 0, "codes": set()})
        g["count"] += count; g["codes"].add(str(code or "—"))
    return [{**v, "codes": sorted(v["codes"]), "percent": _rate(v["count"], total) or 0} for v in sorted(grouped.values(), key=lambda x: x["count"], reverse=True)]

@router.get("/analytics/heatmap")
def analytics_heatmap(start: str | None = None, end: str | None = None, metric: str = "read", db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    col = {"sent": WhatsAppCampaignRecipient.sent_at, "delivered": WhatsAppCampaignRecipient.delivered_at, "failed": WhatsAppCampaignRecipient.failed_at}.get(metric, WhatsAppCampaignRecipient.read_at)
    rows = db.execute(select(func.extract("dow", col), func.extract("hour", col), func.count(WhatsAppCampaignRecipient.id)).join(WhatsAppCampaign, WhatsAppCampaign.id == WhatsAppCampaignRecipient.campaign_id).where(WhatsAppCampaign.tenant_id == tenant.id, col >= start_dt, col <= end_dt).group_by(func.extract("dow", col), func.extract("hour", col))).all()
    if sum(c for _, _, c in rows) < 10: return {"sufficient_data": False, "items": []}
    return {"sufficient_data": True, "items": [{"weekday": int(d), "hour": int(h), "count": c} for d, h, c in rows]}

@router.get("/analytics/export")
def analytics_export(type: str = "campaigns", start: str | None = None, end: str | None = None, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    start_dt, end_dt = _analytics_bounds(start, end)
    out = io.StringIO(); writer = csv.writer(out); out.write("\ufeff")
    if type == "templates":
        writer.writerow(["Template", "Categoria", "Idioma", "Campanhas", "Destinatários", "Enviadas", "Entregues", "Lidas", "Falhas"])
        for item in analytics_by_template(start, end, db=db, tenant=tenant): writer.writerow([item["template_name"], item["category"], item["language"], item["campaigns"], item["total_recipients"], item["total_sent"], item["total_delivered"], item["total_read"], item["total_failed"]])
    elif type == "failures":
        writer.writerow(["Categoria", "Quantidade", "Percentual", "Códigos", "Recomendação"])
        for item in analytics_failures(start, end, db=db, tenant=tenant): writer.writerow([item["category"], item["count"], item["percent"], "; ".join(item["codes"]), item["recommendation"]])
    else:
        writer.writerow(["Campanha", "Status", "Destinatários", "Enviadas", "Entregues", "Lidas", "Falhas", "Criada em"])
        rows = db.execute(_campaign_filters(select(WhatsAppCampaign), tenant.id, start_dt, end_dt).order_by(WhatsAppCampaign.created_at.desc())).scalars().yield_per(500)
        for c in rows: writer.writerow([c.name, c.status, c.total_recipients, c.total_sent, c.total_delivered, c.total_read, c.total_failed, c.created_at.isoformat() if c.created_at else ""])
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=relatorios-campanhas-{type}.csv"})


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _serialize_campaign(c)


@router.put("/{campaign_id}")
def update_campaign(campaign_id: str, payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status not in {"draft", "paused"}:
        raise HTTPException(status_code=409, detail="Apenas campanhas em rascunho ou pausadas podem ser editadas")

    if "name" in payload:
        c.name = str(payload.get("name") or "Campanha").strip() or "Campanha"
    if "provider_id" in payload:
        c.provider_id = payload.get("provider_id")
    if "template_id" in payload:
        c.template_id = payload.get("template_id")
    if "scheduled_at" in payload:
        raw_scheduled_at = payload.get("scheduled_at")
        c.scheduled_at = datetime.fromisoformat(raw_scheduled_at) if raw_scheduled_at else None
    if "metadata_json" in payload and isinstance(payload.get("metadata_json"), dict):
        c.metadata_json = payload.get("metadata_json") or {}
    c.updated_at = datetime.utcnow()
    db.commit(); db.refresh(c)
    return _serialize_campaign(c)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status == "running":
        raise HTTPException(status_code=409, detail="Pause a campanha antes de excluir")
    db.delete(c); db.commit()
    return {"deleted": True}


@router.post("/{campaign_id}/recipients/import")
def import_recipients(campaign_id: str, payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    recipients = payload.get("recipients") or []

    imported = 0
    for item in recipients:
        if not item.get("phone"):
            continue
        db.add(WhatsAppCampaignRecipient(campaign_id=c.id, phone=item.get("phone"), first_name=item.get("first_name"), variables_json=item.get("variables_json") or {}))
        imported += 1
    c.total_recipients = int(c.total_recipients or 0) + imported
    db.commit()
    return {"ok": True, "imported": imported}



@router.post("/{campaign_id}/recipients/import-from-contacts")
def import_recipients_from_contacts(campaign_id: str, payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    ids = payload.get("contact_ids") or []
    if not ids:
        return {"ok": True, "imported": 0}
    contacts = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id.in_(ids))).scalars().all()
    variable_mapping = payload.get("variable_mapping") or {}
    manual_values = payload.get("manual_variable_values") or {}
    variable_mapping_payload = payload.get("variable_mapping_payload") or {}

    def _resolve_contact_value(contact: Contact, mapping_key: str, template_var: str) -> str:
        custom = contact.custom_fields_json or {}
        first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
        if mapping_key == "first_name":
            return str(contact.first_name or "").strip() or first_name_from_name or "cliente"
        if mapping_key in {"full_name", "name"}:
            return str(contact.name or "").strip() or "cliente"
        if mapping_key == "phone":
            return str(contact.phone or "").strip()
        if mapping_key == "email":
            return str(contact.email or "").strip()
        if mapping_key == "order_number":
            return str(custom.get("order_number") or custom.get("pedido") or "").strip()
        if mapping_key == "manual_value":
            return str(manual_values.get(template_var) or "").strip()
        return ""


    def _resolve_mapping_payload(contact: Contact, template_var: str) -> tuple[str, str | None]:
        mapping = variable_mapping_payload.get(str(template_var)) or {}
        mapping_type = str(mapping.get("type") or "").strip()
        field = str(mapping.get("field") or "").strip()
        if mapping_type == "fixed":
            return str(mapping.get("value") or "").strip(), None
        if mapping_type == "contact_field":
            if field == "first_name":
                first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
                return str(contact.first_name or "").strip() or first_name_from_name or "cliente", None
            if field in {"full_name", "name"}:
                return str(contact.name or "").strip() or "cliente", None
            if field == "phone":
                return str(contact.phone or "").strip(), None
            if field == "email":
                return str(contact.email or "").strip(), None
            return "", None
        if mapping_type == "custom_field":
            custom = contact.custom_fields_json if isinstance(contact.custom_fields_json, dict) else {}
            value = str(custom.get(field) or "").strip()
            if not value:
                return "", f"Campo personalizado {field} não existe para este contato. Use valor fixo ou importe esse campo no contato."
            return value, None
        return _resolve_contact_value(contact, str(variable_mapping.get(str(template_var)) or ""), str(template_var)), None

    imported = 0
    for contact in contacts:
        exists = db.execute(
            select(WhatsAppCampaignRecipient)
            .join(WhatsAppCampaign, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
            .where(
                WhatsAppCampaign.tenant_id == tenant.id,
                WhatsAppCampaignRecipient.campaign_id == c.id,
                WhatsAppCampaignRecipient.phone == contact.phone,
            )
        ).scalars().first()
        if exists:
            continue
        first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
        variables = {
            "first_name": str(contact.first_name or "").strip() or first_name_from_name or "cliente",
            "name": str(contact.name or "").strip() or "cliente",
            "phone": str(contact.phone or "").strip(),
            "order_number": str((contact.custom_fields_json or {}).get("order_number") or "").strip(),
        }
        mapping_errors: dict[str, str] = {}
        for template_var, mapping_key in variable_mapping.items():
            resolved_value, resolved_error = _resolve_mapping_payload(contact, str(template_var)) if variable_mapping_payload else (_resolve_contact_value(contact, str(mapping_key), str(template_var)), None)
            variables[str(template_var)] = resolved_value
            if resolved_error:
                mapping_errors[str(template_var)] = resolved_error
        variables["_variable_mapping"] = variable_mapping_payload
        if mapping_errors:
            variables["_variable_mapping_errors"] = mapping_errors
        db.add(WhatsAppCampaignRecipient(campaign_id=c.id, phone=contact.phone, first_name=contact.first_name or contact.name, variables_json=variables))
        imported += 1
    c.total_recipients = int(c.total_recipients or 0) + imported
    db.commit()
    return {"ok": True, "imported": imported}

@router.post("/{campaign_id}/start")
def start_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status == "running":
        raise HTTPException(status_code=400, detail="Campaign is already running")
    provider = db.execute(
        select(TenantWhatsAppProvider).where(
            TenantWhatsAppProvider.id == c.provider_id,
            TenantWhatsAppProvider.tenant_id == tenant.id,
        )
    ).scalars().first()
    if not provider or provider.status != "connected":
        raise HTTPException(status_code=400, detail="Provider is not connected/active")
    template = db.execute(
        select(WhatsAppMessageTemplate).where(
            WhatsAppMessageTemplate.id == c.template_id,
            WhatsAppMessageTemplate.tenant_id == tenant.id,
        )
    ).scalars().first()
    if not template or str(template.status or "").lower() != "approved":
        raise HTTPException(status_code=400, detail="Template is not approved")
    recipients = db.execute(
        select(WhatsAppCampaignRecipient)
        .join(WhatsAppCampaign, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
        .where(WhatsAppCampaign.tenant_id == tenant.id, WhatsAppCampaignRecipient.campaign_id == c.id)
    ).scalars().all()
    if not recipients:
        raise HTTPException(status_code=400, detail="Campaign has no recipients")
    required_vars = _extract_template_variables(template)
    if required_vars:
        for rec in recipients:
            vars_json = rec.variables_json if isinstance(rec.variables_json, dict) else {}
            missing = [var for var in required_vars if not str(vars_json.get(var) or "").strip()]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Faltou preencher {', '.join(missing)}.",
                )
    if c.scheduled_at and c.scheduled_at > datetime.utcnow():
        c.status = "scheduled"
        db.commit()
        get_queue("normal").enqueue_at(c.scheduled_at, "app.workers.campaign_worker.process_campaign", str(c.id), str(tenant.id), job_timeout=600)
        db.refresh(c)
        return _serialize_campaign(c)
    c.status = "running"
    c.started_at = c.started_at or datetime.utcnow()
    db.commit()
    get_queue("normal").enqueue("app.workers.campaign_worker.process_campaign", str(c.id), str(tenant.id), job_timeout=600)
    db.refresh(c)
    return _serialize_campaign(c)


@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status not in {"running", "scheduled"}:
        raise HTTPException(status_code=409, detail="Apenas campanhas agendadas ou em execução podem ser pausadas")
    c.status = "paused"
    c.updated_at = datetime.utcnow()
    db.commit(); db.refresh(c)
    return _serialize_campaign(c)


@router.post("/{campaign_id}/resume")
def resume_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status != "paused":
        raise HTTPException(status_code=409, detail="Apenas campanhas pausadas podem ser retomadas")
    c.status = "running"
    c.started_at = c.started_at or datetime.utcnow()
    c.updated_at = datetime.utcnow()
    db.commit()
    get_queue("normal").enqueue("app.workers.campaign_worker.process_campaign", str(c.id), str(tenant.id), job_timeout=600)
    db.refresh(c)
    return _serialize_campaign(c)


@router.post("/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status not in {"scheduled", "running", "paused"}:
        raise HTTPException(status_code=409, detail="Campanha não pode ser cancelada neste status")
    c.status = "cancelled"
    c.completed_at = c.completed_at or datetime.utcnow()
    metadata = c.metadata_json if isinstance(c.metadata_json, dict) else {}
    metadata.update({"cancelled_by": "console", "cancelled_at": datetime.utcnow().isoformat()})
    c.metadata_json = metadata
    c.updated_at = datetime.utcnow()
    db.commit(); db.refresh(c)
    return _serialize_campaign(c)


@router.get("/{campaign_id}/recipients")
def list_recipients(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rows = db.execute(
        select(WhatsAppCampaignRecipient)
        .join(WhatsAppCampaign, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
        .where(WhatsAppCampaign.tenant_id == tenant.id, WhatsAppCampaignRecipient.campaign_id == c.id)
        .order_by(WhatsAppCampaignRecipient.created_at.desc())
    ).scalars().all()
    return [{"id": str(r.id), "campaign_id": str(r.campaign_id), "phone": r.phone, "first_name": r.first_name, "status": r.status, "provider_message_id": r.provider_message_id, "error_message": r.error_message, "sent_at": r.sent_at.isoformat() if r.sent_at else None, "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None, "read_at": r.read_at.isoformat() if r.read_at else None, "failed_at": r.failed_at.isoformat() if r.failed_at else None} for r in rows]
