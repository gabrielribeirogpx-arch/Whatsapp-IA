from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Flow, KnowledgeBase, PipelineStage
from app.models.audit_log import AuditLog
from app.models.marketplace_installation import MarketplaceInstallation, MarketplaceInstallationResource
from app.models.product_analytics import ProductEvent

VARIANTS = {"Sem IA", "Híbrida", "IA Completa"}
FLOWS = ["Recepção inicial", "Qualificação do paciente", "Agendamento", "Confirmação", "Reagendamento", "Cancelamento", "Lembrete", "Pós-consulta", "Pesquisa de satisfação", "Recuperação de paciente inativo", "Transferência humana"]
PIPELINE = ["Novo paciente", "Triagem realizada", "Consulta solicitada", "Consulta agendada", "Confirmado", "Compareceu", "Tratamento em andamento", "Retorno previsto", "Concluído", "Não compareceu", "Recuperação"]
TAGS = ["primeira_consulta", "retorno", "urgencia", "particular", "convenio", "implante", "ortodontia", "avaliacao_pendente", "paciente_inativo", "handoff_humano"]
FIELDS = ["tipo de atendimento", "especialidade", "convênio", "primeira consulta", "urgência", "profissional responsável", "data da última consulta", "retorno previsto", "origem do lead"]
CHECKLIST = ["conectar WhatsApp", "revisar horário de atendimento", "configurar Google Calendar", "revisar profissionais", "revisar especialidades", "ajustar copies", "testar agendamento", "testar handoff", "publicar fluxos", "executar primeiro teste ponta a ponta"]
COPIES = {"Recepção inicial": "Olá, {{nome}}! Como podemos ajudar com seu atendimento?", "Confirmação": "Seu atendimento está reservado para {{data}} às {{hora}}. Posso confirmar sua presença?", "Lembrete": "Lembrete: esperamos você em {{data}} às {{hora}}. Responda para confirmar ou reagendar.", "Transferência humana": "Vou transferir você para nossa equipe. Se a transferência falhar, deixe sua mensagem e retornaremos."}

def dentistry_manifest(variant: str) -> dict:
    if variant not in VARIANTS: raise ValueError("variant_not_supported")
    uses_ai = variant != "Sem IA"
    return {"slug": "clinica_odontologica", "version": "1.0.0", "variant": variant, "flows": FLOWS, "pipeline_stages": PIPELINE, "tags": TAGS, "custom_fields": FIELDS, "knowledge_bases": ["Clínica Odontológica — Conhecimento inicial"] if uses_ai else [], "ai_agents": ["Agente de atendimento odontológico"] if uses_ai else [], "dashboards": ["Operação odontológica"], "academy": ["Operação odontológica"], "documentation": ["Guia da operação"], "checklist": CHECKLIST, "methodologies": ["initial-service@1.0.0", "qualification@1.0.0", "scheduling@1.0.0", "human-handoff@1.0.0"], "post_install_steps": CHECKLIST}

class MarketplaceInstallationService:
    def __init__(self, db: Session, tenant, user): self.db, self.tenant, self.user = db, tenant, user
    def _assert_access(self):
        if str(self.user.tenant_id) != str(self.tenant.id) or self.user.status != "active": raise PermissionError("tenant_or_user_invalid")
        if self.user.role not in {"owner", "admin"}: raise PermissionError("marketplace_install_forbidden")
    def preview(self, slug: str, variant: str) -> dict:
        self._assert_access()
        if slug != "clinica_odontologica": raise LookupError("template_not_found")
        manifest = dentistry_manifest(variant)
        unsupported = {"ai_agents": "capability_not_supported", "tags": "capability_not_supported", "custom_fields": "capability_not_supported", "dashboards": "capability_not_supported", "academy": "preview_only", "documentation": "preview_only"}
        classification = {key: (unsupported.get(key) or ("materialized" if key in {"flows", "pipeline_stages", "knowledge_bases", "checklist"} else "preview_only")) for key in ["flows", "nodes", "edges", "ai_agents", "knowledge_bases", "pipelines", "pipeline_stages", "tags", "custom_fields", "dashboards", "academy", "documentation", "checklist", "methodologies", "post_install_steps"]}
        classification.update(nodes="materialized", edges="materialized", pipelines="partially_supported")
        missing = ["google_calendar"] if variant != "Sem IA" else []
        return {"manifest": manifest, "capabilities": classification, "missing_integrations": missing, "resulting_status": "needs_configuration" if missing or any(v in {"capability_not_supported", "preview_only"} for v in classification.values()) else "completed"}
    def _event(self, name, installation):
        now = datetime.now(timezone.utc)
        self.db.add(ProductEvent(tenant_id=self.tenant.id, user_id=self.user.id, event_name=name, source="backend", occurred_at=now, received_at=now, properties={"installation_id": str(installation.id), "template_slug": installation.template_slug, "variant": installation.variant}, context={}, idempotency_key=f"{installation.id}:{name}", created_at=now))
        self.db.add(AuditLog(tenant_id=self.tenant.id, user_id=self.user.id, action=name, entity_type="marketplace_installation", entity_id=str(installation.id), metadata_json={"template_slug": installation.template_slug, "variant": installation.variant}))
    def _track(self, installation, kind, obj_id, name, metadata=None, status="created"):
        self.db.add(MarketplaceInstallationResource(installation_id=installation.id, resource_type=kind, resource_id=str(obj_id), resource_name=name, creation_status=status, metadata_json=metadata or {}))
    def install(self, slug: str, variant: str, key: str):
        self._assert_access()
        previous = self.db.scalar(select(MarketplaceInstallation).where(MarketplaceInstallation.tenant_id == self.tenant.id, MarketplaceInstallation.idempotency_key == key))
        if previous: return previous
        preview = self.preview(slug, variant); manifest = preview["manifest"]
        installation = MarketplaceInstallation(tenant_id=self.tenant.id, template_id=slug, template_slug=slug, template_type="business_kit", template_version=manifest["version"], automation_level=variant, variant=variant, status="pending", idempotency_key=key, installed_by_user_id=self.user.id, manifest_snapshot=manifest, dependency_snapshot={"missing_integrations": preview["missing_integrations"]}, customization_state={"checklist": [{"key": str(i), "label": label, "status": "blocked" if label == "configurar Google Calendar" and variant != "Sem IA" else "pending"} for i, label in enumerate(CHECKLIST)]}, created_resources={})
        self.db.add(installation); self.db.flush(); self._event("template_install_started", installation)
        try:
            created = {}
            for flow_name in FLOWS:
                ids = [str(uuid.uuid4()) for _ in range(3)]; copy = COPIES.get(flow_name, f"Vamos continuar com {flow_name.lower()}, {{nome}}. Se precisar, solicite atendimento humano.")
                node_types = ["start", "message", "human_handoff" if flow_name == "Transferência humana" else "end"]
                nodes = [{"id": ids[i], "type": node_types[i], "position": {"x": i * 280, "y": 80}, "data": {"label": flow_name if i == 1 else node_types[i], "message": copy if i == 1 else "", "copy": {"tone": "acolhedor", "objective": flow_name, "fallback": "Solicite atendimento humano."} if i == 1 else {}}} for i in range(3)]
                edges = [{"id": str(uuid.uuid4()), "source": ids[i], "target": ids[i+1]} for i in range(2)]
                flow = Flow(tenant_id=self.tenant.id, name=f"Odonto · {flow_name}", description=f"Marketplace installation {installation.id}", runtime="v2", status="draft", nodes=nodes, edges=edges, nodes_json=nodes, edges_json=edges)
                self.db.add(flow); self.db.flush(); self._track(installation, "flow", flow.id, flow.name, {"ownership": str(installation.id), "copies": [{"node_id": ids[1], "category": flow_name}]}); created.setdefault("flows", []).append(str(flow.id))
            position = self.db.scalar(select(func.max(PipelineStage.position)).where(PipelineStage.tenant_id == self.tenant.id)) or -1
            for stage_name in PIPELINE:
                existing = self.db.scalar(select(PipelineStage).where(PipelineStage.tenant_id == self.tenant.id, PipelineStage.name == stage_name))
                if existing: self._track(installation, "pipeline_stage", existing.id, stage_name, {"preexisting": True}, "reused")
                else:
                    position += 1; stage = PipelineStage(tenant_id=self.tenant.id, name=stage_name, position=position, is_final_stage=stage_name == "Concluído"); self.db.add(stage); self.db.flush(); self._track(installation, "pipeline_stage", stage.id, stage_name, {"ownership": str(installation.id)}); created.setdefault("pipeline_stages", []).append(str(stage.id))
            for title in manifest["knowledge_bases"]:
                kb = KnowledgeBase(tenant_id=self.tenant.id, title=title, content="Horários, especialidades, convênios e orientações devem ser revisados antes da publicação."); self.db.add(kb); self.db.flush(); self._track(installation, "knowledge_base", kb.id, title, {"ownership": str(installation.id)}); created.setdefault("knowledge_bases", []).append(str(kb.id))
            installation.created_resources = created; installation.status = preview["resulting_status"]; installation.completed_at = datetime.utcnow(); self._event("template_install_completed", installation); self._event("business_kit_installed", installation); self.db.commit(); self.db.refresh(installation); return installation
        except Exception as exc:
            self.db.rollback(); installation.status = "failed"; installation.failed_at = datetime.utcnow(); installation.error_code = "INSTALLATION_FAILED"; installation.error_summary = type(exc).__name__; self.db.add(installation); self._event("template_install_failed", installation); self.db.commit(); raise
    def rollback(self, installation):
        if installation.status == "rolled_back": return installation
        partial = False
        for resource in installation.resources:
            if resource.creation_status != "created": resource.rollback_status = "not_applicable"; continue
            model = {"flow": Flow, "pipeline_stage": PipelineStage, "knowledge_base": KnowledgeBase}.get(resource.resource_type)
            obj = self.db.get(model, uuid.UUID(resource.resource_id)) if model else None
            if obj is not None and str(getattr(obj, "tenant_id", "")) == str(self.tenant.id): self.db.delete(obj); resource.rollback_status = "removed"
            else: resource.rollback_status = "not_found"; partial = True
        installation.status = "partially_rolled_back" if partial else "rolled_back"; self._event("template_install_rolled_back", installation); self.db.commit(); return installation
