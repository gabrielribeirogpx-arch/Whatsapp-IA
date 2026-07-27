from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.marketplace_assets import MarketplaceGraphValidator, get_asset, get_item
from app.models import Flow, KnowledgeBase, PipelineStage
from app.models.audit_log import AuditLog
from app.models.marketplace_installation import MarketplaceInstallation, MarketplaceInstallationResource
from app.models.product_analytics import ProductEvent

VARIANTS = {"Sem IA", "Híbrida", "IA Completa"}
VARIANT_KEYS = {"Sem IA": "no_ai", "Híbrida": "hybrid", "IA Completa": "full_ai", "Híbrido": "hybrid"}
FLOWS = ["Menu Principal", "Primeira Consulta", "Emergência", "Avaliação", "Orçamento", "Confirmação", "Reagendamento", "Cancelamento", "Pós Consulta", "Pesquisa", "Recuperação", "Financeiro"]
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
    def _resolve(self, slug: str, variant: str):
        item = get_item(slug); variant_key = VARIANT_KEYS.get(variant, variant)
        if item["availability"] != "installable_real": raise ValueError("capability_not_supported")
        if variant_key not in item["variants"]: raise ValueError("variant_not_supported")
        assets = [get_asset(key) for key in item["flow_assets"]]
        if slug == "clinica_odontologica" and variant_key != "no_ai":
            # Keep the deterministic operation as the backbone and make AI explicit
            # only in the flows where it adds value. Each transformed graph remains
            # visible; no ai_system wrapper is introduced.
            limit = len(assets) if variant_key == "full_ai" else 4
            for asset in assets[:limit]:
                asset["metadata"]["automation_level"] = variant_key
                asset["supported_variants"] = [variant_key]
                graph = asset["graph"]; previous = graph["nodes"][1]["key"]; target = graph["nodes"][2]["key"]
                ai_key = "ai_interpretation"
                graph["nodes"].insert(2, {"key": ai_key, "type": "ai_classification", "position": {"x": 420, "y": 180}, "config": {"label": "Interpretação odontológica", "classes": ["consulta", "especialidade", "urgência", "convênio", "retorno"], "fallback": "human_handoff"}})
                graph["edges"] = [edge for edge in graph["edges"] if not (edge["source"] == previous and edge["target"] == target)] + [{"source": previous, "target": ai_key}, {"source": ai_key, "target": target}]
                asset["required_node_types"] = sorted(set(asset["required_node_types"]) | {"ai_classification"})
                asset["educational_metadata"][ai_key] = {"purpose": "Interpretar intenção odontológica sem tomar a decisão operacional", "when_to_use": "Use depois da contextualização e antes da regra determinística.", "best_practices": ["Defina classes fechadas", "Mantenha fallback humano", "Monitore confiança"], "alternatives": ["choice", "condition"], "common_mistakes": ["Permitir classes livres", "Remover o fallback"], "input": "mensagem do paciente", "output": "intenção classificada", "why_here": "Apoia a rota determinística sem substituir regras e handoff."}
        validator = MarketplaceGraphValidator()
        for asset in assets: validator.validate(asset)
        return item, variant_key, assets
    def preview(self, slug: str, variant: str) -> dict:
        self._assert_access(); item, variant_key, assets = self._resolve(slug, variant)
        manifest = dentistry_manifest(variant) if slug == "clinica_odontologica" else {**item, "variant": variant_key, "flows": [a["key"] for a in assets]}
        missing = sorted({integration for asset in assets for integration in asset["required_integrations"]})
        return {"manifest": manifest, "assets": assets, "capabilities": {"flows": "materialized", "nodes": "materialized", "edges": "materialized", "blueprint": "materialized" if item["template_type"] == "business_kit" else "not_applicable"}, "missing_integrations": missing, "resulting_status": "needs_configuration" if missing else "completed", "post_install_route": "business_builder" if item["template_type"] == "business_kit" else "flow_builder"}
    def _event(self, name, installation):
        now = datetime.now(timezone.utc)
        self.db.add(ProductEvent(tenant_id=self.tenant.id, user_id=self.user.id, event_name=name, source="backend", occurred_at=now, received_at=now, properties={"installation_id": str(installation.id), "template_slug": installation.template_slug, "variant": installation.variant}, context={}, idempotency_key=f"{installation.id}:{name}", created_at=now))
        self.db.add(AuditLog(tenant_id=self.tenant.id, user_id=self.user.id, action=name, entity_type="marketplace_installation", entity_id=str(installation.id), metadata_json={"template_slug": installation.template_slug, "variant": installation.variant}))
    def _track(self, installation, kind, obj_id, name, metadata=None, status="created"):
        self.db.add(MarketplaceInstallationResource(installation_id=installation.id, resource_type=kind, resource_id=str(obj_id), resource_name=name, creation_status=status, metadata_json=metadata or {}))
    @staticmethod
    def _materialize(asset):
        ids = {node["key"]: str(uuid.uuid4()) for node in asset["graph"]["nodes"]}
        nodes = [{"id": ids[node["key"]], "type": node["type"], "position": node["position"], "data": {**node["config"], "marketplace_asset_key": asset["key"], "educational_metadata": asset["educational_metadata"].get(node["key"], {})}} for node in asset["graph"]["nodes"]]
        edges = []
        for edge in asset["graph"]["edges"]:
            source_handle = edge.get("sourceHandle", edge.get("source_handle"))
            target_handle = edge.get("targetHandle", edge.get("target_handle"))
            materialized = {
                **{key: value for key, value in edge.items() if key not in {"id", "source", "target", "source_handle", "target_handle", "sourceHandle", "targetHandle"}},
                "id": str(uuid.uuid4()),
                "source": ids[edge["source"]],
                "target": ids[edge["target"]],
                "type": edge.get("type", "default"),
            }
            if source_handle is not None:
                materialized["sourceHandle"] = source_handle
            if target_handle is not None:
                materialized["targetHandle"] = target_handle
            edges.append(materialized)
        return nodes, edges
    def install(self, slug: str, variant: str, key: str):
        self._assert_access()
        previous = self.db.scalar(select(MarketplaceInstallation).where(MarketplaceInstallation.tenant_id == self.tenant.id, MarketplaceInstallation.idempotency_key == key))
        if previous: return previous
        preview = self.preview(slug, variant); item, variant_key, assets = self._resolve(slug, variant); manifest = preview["manifest"]
        installation = MarketplaceInstallation(tenant_id=self.tenant.id, template_id=slug, template_slug=slug, template_type=item["template_type"], template_version=item["version"], automation_level=variant_key, variant=variant, status="pending", idempotency_key=key, installed_by_user_id=self.user.id, manifest_snapshot=manifest, dependency_snapshot={"missing_integrations": preview["missing_integrations"]}, customization_state={"checklist": []}, created_resources={})
        self.db.add(installation); self.db.flush(); self._event("template_install_started", installation)
        try:
            created = {"flows": []}
            for asset in assets:
                nodes, edges = self._materialize(asset)
                flow = Flow(tenant_id=self.tenant.id, name=asset["name"], description=f"Marketplace {asset['key']}@{asset['version']} · installation {installation.id}", runtime="v2", status="draft", nodes=nodes, edges=edges, nodes_json=nodes, edges_json=edges)
                self.db.add(flow); self.db.flush(); self._track(installation, "flow", flow.id, flow.name, {"ownership": str(installation.id), "asset_key": asset["key"], "asset_version": asset["version"]}); created["flows"].append(str(flow.id))
            if item["template_type"] == "business_kit":
                blueprint_id = uuid.uuid4(); created["blueprint_id"] = str(blueprint_id); self._track(installation, "blueprint", blueprint_id, f"Blueprint · {slug}", {"flow_ids": created["flows"], "manifest": item})
            if slug == "clinica_odontologica":
                position = self.db.scalar(select(func.max(PipelineStage.position)).where(PipelineStage.tenant_id == self.tenant.id)) or -1
                for stage_name in PIPELINE:
                    existing = self.db.scalar(select(PipelineStage).where(PipelineStage.tenant_id == self.tenant.id, PipelineStage.name == stage_name))
                    if existing: self._track(installation, "pipeline_stage", existing.id, stage_name, {"preexisting": True}, "reused")
                    else:
                        position += 1; stage = PipelineStage(tenant_id=self.tenant.id, name=stage_name, position=position, is_final_stage=stage_name == "Concluído"); self.db.add(stage); self.db.flush(); self._track(installation, "pipeline_stage", stage.id, stage_name, {"ownership": str(installation.id)}); created.setdefault("pipeline_stages", []).append(str(stage.id))
            created["post_install_route"] = "/dashboard/business-builder" if item["template_type"] == "business_kit" else f"/dashboard/flow-builder?flow_id={created['flows'][0]}"
            installation.created_resources = created; installation.status = preview["resulting_status"]; installation.completed_at = datetime.utcnow(); self._event("template_install_completed", installation); self.db.commit(); self.db.refresh(installation); return installation
        except Exception as exc:
            self.db.rollback(); raise
    def rollback(self, installation):
        if installation.status == "rolled_back": return installation
        partial = False
        for resource in installation.resources:
            if resource.creation_status != "created": resource.rollback_status = "not_applicable"; continue
            model = {"flow": Flow, "pipeline_stage": PipelineStage, "knowledge_base": KnowledgeBase}.get(resource.resource_type)
            obj = self.db.get(model, uuid.UUID(resource.resource_id)) if model else None
            if model is None: resource.rollback_status = "removed"; continue
            if obj is not None and str(getattr(obj, "tenant_id", "")) == str(self.tenant.id): self.db.delete(obj); resource.rollback_status = "removed"
            else: resource.rollback_status = "not_found"; partial = True
        installation.status = "partially_rolled_back" if partial else "rolled_back"; self._event("template_install_rolled_back", installation); self.db.commit(); return installation
