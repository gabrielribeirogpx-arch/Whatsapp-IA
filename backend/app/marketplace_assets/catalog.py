from __future__ import annotations

from copy import deepcopy
from typing import Any

NODE_TYPES = {"start", "message", "choice", "condition", "delay", "action", "media", "cta_url", "ai_rag", "ai_response", "ai_classification", "ai_extraction", "ai_summary", "ai_agent", "ai_supervisor"}


def _graph(steps: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    nodes = []
    for index, (key, kind, config) in enumerate(steps):
        data = {"label": config.get("label", key.replace("_", " ").title()), **config}
        if index == 0:
            data["isStart"] = True
        if index == len(steps) - 1:
            data.update({"isEnd": True, "is_terminal": True, "endFlow": True})
        nodes.append({"key": key, "type": kind, "position": {"x": index * 280, "y": (index % 2) * 100}, "config": data})
    return {"nodes": nodes, "edges": [{"source": steps[i][0], "target": steps[i + 1][0]} for i in range(len(steps) - 1)]}


def _asset(key: str, name: str, level: str, steps: list[tuple[str, str, dict[str, Any]]], *, segment: str = "geral", integrations: tuple[str, ...] = ()) -> dict[str, Any]:
    graph = _graph(steps)
    return {"key": key, "version": "1.0.0", "type": "flow_template" if level == "no_ai" else "ai_composition", "name": name, "description": f"{name}: automação materializada e editável.", "supported_variants": [level], "required_node_types": sorted({n["type"] for n in graph["nodes"]}), "required_integrations": list(integrations), "graph": graph, "metadata": {"segment": segment, "automation_level": level}, "educational_metadata": {n["key"]: {"purpose": n["config"]["label"], "input": "contexto anterior", "output": "contexto atualizado", "why_here": f"Executa a etapa {n['config']['label']}."} for n in graph["nodes"]}, "compatibility": {"runtime": "v2", "minimum_schema": 1}}


def _steps(name: str, middle: str, objective: str) -> list[tuple[str, str, dict[str, Any]]]:
    return [("start", "start", {"label": "Início"}), ("welcome", "message", {"content": f"Olá, {{{{contact.name}}}}! {objective}", "message": f"Olá, {{{{contact.name}}}}! {objective}"}), (middle, "choice" if middle != "route" else "condition", {"options": ["Continuar", "Falar com a equipe"], "condition": name}), ("register", "action", {"action": "update_contact", "fields": {"marketplace_origin": name}}), ("finish", "message", {"content": "Tudo certo. Se precisar, nossa equipe está disponível.", "message": "Tudo certo. Se precisar, nossa equipe está disponível."})]


NO_AI = {
    "menu_inicial": ("Menu inicial", "menu", "Escolha uma opção para começar."),
    "atendimento_por_setor": ("Atendimento por setor", "route", "Qual setor você deseja falar?"),
    "qualificacao_de_lead": ("Qualificação de lead", "profile", "Conte um pouco sobre sua necessidade."),
    "agendamento_simples": ("Agendamento simples", "schedule", "Vamos escolher o melhor período."),
    "follow_up": ("Follow-up", "response", "Gostaria de continuar seu atendimento?"),
    "pesquisa_nps": ("Pesquisa NPS", "score", "De 0 a 10, como foi sua experiência?"),
    "cobranca": ("Cobrança", "payment", "Enviamos os dados da sua pendência."),
    "transferencia_humana": ("Transferência humana", "handoff_queue", "Vou direcionar você à equipe."),
    "faq_estruturado": ("FAQ estruturado", "topics", "Escolha o assunto da sua dúvida."),
    "coleta_de_dados": ("Coleta de dados", "fields", "Precisamos confirmar alguns dados."),
}

HYBRID = {
    "atendimento_com_fallback_para_ia": "Atendimento com fallback para IA", "qualificacao_inteligente": "Qualificação inteligente",
    "agendamento_hibrido": "Agendamento híbrido", "faq_com_rag": "FAQ com RAG", "crm_assistido_por_ia": "CRM assistido por IA",
    "comercial_com_handoff": "Comercial com handoff", "recuperacao_de_lead_com_ia": "Recuperação de lead com IA",
}

ASSETS: dict[str, dict[str, Any]] = {key: _asset(key, name, "no_ai", _steps(name, middle, objective)) for key, (name, middle, objective) in NO_AI.items()}
for key, name in HYBRID.items():
    ai_type = "ai_rag" if key == "faq_com_rag" else "ai_classification"
    steps = _steps(name, "route", "Vamos entender sua solicitação.")
    steps.insert(3, ("ai_assist", ai_type, {"prompt": f"Auxilie somente na etapa de {name}.", "fallback": "human_handoff"}))
    steps.insert(-1, ("handoff", "action", {"action": "human_handoff", "queue": "atendimento"}))
    ASSETS[key] = _asset(key, name, "hybrid", steps)

for key, name, focus in [("agenda_inteligente", "Agenda Inteligente", "agendamento"), ("atendimento_inteligente", "Atendimento Inteligente", "atendimento"), ("comercial_inteligente", "Comercial Inteligente", "comercial")]:
    steps = [("start", "start", {"label": "Início"}), ("context", "message", {"content": f"Iniciando {focus} com contexto."}), ("intent", "ai_classification", {"classes": [focus, "humano"]}), ("knowledge", "ai_rag", {"query": "{{message.text}}"}), ("agent", "ai_agent", {"prompt": f"Especialista em {focus}", "guardrails": True}), ("safety", "condition", {"condition": "confidence >= 0.8"}), ("crm", "action", {"action": "update_contact"}), ("handoff", "action", {"action": "human_handoff"}), ("finish", "message", {"content": "Atendimento concluído."})]
    ASSETS[key] = _asset(key, name, "full_ai", steps)

DENTAL_NAMES = ["Recepção odontológica", "Identificação do paciente", "Qualificação de atendimento", "Agendamento", "Confirmação", "Reagendamento", "Cancelamento", "Lembrete", "Pós-consulta", "Pesquisa de satisfação", "Recuperação de paciente inativo", "Transferência humana"]
for index, name in enumerate(DENTAL_NAMES):
    key = "odontologia_" + name.lower().replace("ç", "c").replace("ã", "a").replace("ó", "o").replace("ê", "e").replace(" ", "_").replace("-", "_")
    objective = ["Você busca consulta, retorno ou urgência?", "É sua primeira consulta conosco?", "Qual especialidade, convênio e nível de urgência?", "Qual período prefere para sua consulta?", "Podemos confirmar sua consulta odontológica?", "Escolha um novo período para sua consulta.", "Confirme o cancelamento da consulta.", "Sua consulta odontológica está próxima.", "Como você está após sua consulta?", "De 0 a 10, como avalia seu atendimento odontológico?", "Sentimos sua falta. Deseja agendar uma avaliação?", "Vou transferir seu histórico para nossa recepção."][index]
    steps = _steps(name, "route" if index in {0, 2, 11} else f"dental_step_{index}", objective)
    if index in {2, 3, 5}:
        steps.insert(-1, ("dental_record", "action", {"action": "update_contact", "fields": {"especialidade": "{{answer}}", "convenio": "{{contact.convenio}}"}}))
    ASSETS[key] = _asset(key, name, "no_ai", steps, segment="odontologia")

SEGMENT_ASSETS = {"imobiliaria_recepcao": ("Imobiliária · Busca de imóvel", "Você quer comprar ou alugar? Informe bairro, quartos e faixa de preço."), "restaurante_pedido": ("Restaurante · Pedido", "Você deseja delivery ou retirada? Vamos escolher cardápio e pagamento."), "advocacia_triagem": ("Advocacia · Triagem", "Informe a área jurídica e urgência. A equipe validará conflito de interesse.")}
for key, (name, objective) in SEGMENT_ASSETS.items():
    steps = _steps(name, "route", objective)
    if key == "advocacia_triagem": steps.insert(-1, ("mandatory_handoff", "action", {"action": "human_handoff", "reason": "legal_review"}))
    ASSETS[key] = _asset(key, name, "no_ai", steps, segment=key.split("_")[0])

ITEMS: dict[str, dict[str, Any]] = {}
for key in [*NO_AI, *HYBRID, "agenda_inteligente", "atendimento_inteligente", "comercial_inteligente"]:
    kind = "flow_template" if key in NO_AI else "hybrid_flow" if key in HYBRID else "ai_system"
    ITEMS[key] = {"key": key, "version": "1.0.0", "template_type": kind, "availability": "installable_real", "variants": ASSETS[key]["supported_variants"], "flow_assets": [key]}
ITEMS["clinica_odontologica"] = {"key": "clinica_odontologica", "version": "1.0.0", "template_type": "business_kit", "availability": "installable_real", "variants": ["no_ai", "hybrid", "full_ai"], "flow_assets": [k for k in ASSETS if k.startswith("odontologia_")], "pipeline": "odontologia_pipeline@1.0.0"}
for segment, asset in [("imobiliaria", "imobiliaria_recepcao"), ("restaurante", "restaurante_pedido"), ("advocacia", "advocacia_triagem")]:
    ITEMS[segment] = {"key": segment, "version": "1.0.0", "template_type": "business_kit", "availability": "installable_real", "variants": ["no_ai"], "flow_assets": [asset]}

def get_asset(key: str) -> dict[str, Any]:
    if key not in ASSETS: raise LookupError("asset_not_found")
    return deepcopy(ASSETS[key])

def get_item(key: str) -> dict[str, Any]:
    if key not in ITEMS: raise LookupError("template_not_found")
    return deepcopy(ITEMS[key])
