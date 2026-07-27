"""Production-grade, declarative Marketplace graphs for Runtime V2.

The catalogue deliberately stores ordinary canvas nodes.  Nothing is hidden in a
wrapper: installation gives the customer the same graph an automation architect
would build by hand.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

NODE_TYPES = {"start", "message", "choice", "condition", "delay", "action", "media", "cta_url", "ai_rag", "ai_response", "ai_classification", "ai_extraction", "ai_summary", "ai_agent", "ai_supervisor"}


def _education(label: str, kind: str) -> dict[str, Any]:
    alternatives = {"choice": ["condition", "message"], "condition": ["choice"], "delay": ["action"], "action": ["message"]}.get(kind, ["message", "action"])
    return {
        "purpose": f"Executar {label} com uma responsabilidade única e observável.",
        "when_to_use": f"Use quando a conversa chegar à etapa {label}.",
        "best_practices": ["Mantenha uma única responsabilidade", "Teste todos os caminhos antes de publicar", "Use variáveis com nomes explícitos"],
        "alternatives": alternatives,
        "common_mistakes": ["Não tratar resposta inesperada", "Avançar sem persistir o contexto necessário"],
        "input": "contexto e resposta da etapa anterior",
        "output": "contexto atualizado e rota selecionada",
        "why_here": f"Esta posição garante que {label.lower()} aconteça antes da próxima decisão.",
    }


def _node(key: str, kind: str, label: str, **config: Any) -> tuple[str, str, dict[str, Any]]:
    return key, kind, {"label": label, **config}


def _asset(key: str, name: str, level: str, nodes: list[tuple[str, str, dict[str, Any]]], edges: list[tuple[str, str, str | None]], *, segment: str = "geral", integrations: tuple[str, ...] = ()) -> dict[str, Any]:
    materialized = []
    for index, (node_key, kind, config) in enumerate(nodes):
        data = dict(config)
        if kind == "start": data["isStart"] = True
        materialized.append({"key": node_key, "type": kind, "position": {"x": (index % 5) * 300, "y": (index // 5) * 190}, "config": data})
    terminal_keys = {source for source, _, _ in edges} ^ {target for _, target, _ in edges}
    for node in materialized:
        if node["key"] in terminal_keys and not any(source == node["key"] for source, _, _ in edges):
            node["config"].update({"isEnd": True, "is_terminal": True, "endFlow": True})
    graph_edges = [{"source": source, "target": target, **({"source_handle": handle} if handle else {})} for source, target, handle in edges]
    return {
        "key": key, "version": "2.0.0", "type": "flow_template" if level == "no_ai" else "ai_composition", "name": name,
        "description": f"{name}: operação completa, ramificada e totalmente editável.", "supported_variants": [level],
        "required_node_types": sorted({node[1] for node in nodes}), "required_integrations": list(integrations),
        "graph": {"nodes": materialized, "edges": graph_edges}, "metadata": {"segment": segment, "automation_level": level, "architecture": "visible_runtime_v2"},
        "educational_metadata": {node_key: _education(config["label"], kind) for node_key, kind, config in nodes},
        "compatibility": {"runtime": "v2", "minimum_schema": 1},
    }


def _operational_graph(key: str, name: str, objective: str, *, segment: str = "geral", ai: str | None = None, integration: str | None = None) -> dict[str, Any]:
    """A reusable branched operation: capture, route, CRM, recovery and handoff."""
    p = key
    nodes = [
        _node("start", "start", "Entrada do WhatsApp"),
        _node(f"{p}_welcome", "message", "Contextualização", content=f"Olá, {{{{contact.name}}}}! {objective}"),
        _node(f"{p}_identify", "choice", "Identificação da intenção", options=["Continuar", "Dúvida", "Falar com uma pessoa"], variable=f"{p}_intent"),
        _node(f"{p}_capture", "action", "Persistir dados", action="set_variables", fields={f"{p}_origin": "marketplace", f"{p}_intent": "{{answer}}"}),
        _node(f"{p}_route", "condition", "Roteamento principal", condition=f"{{{{{p}_intent}}}}", branches=["success", "fallback", "human"]),
        _node(f"{p}_qualify", "choice", "Pergunta de qualificação", options=["Alta prioridade", "Posso aguardar", "Só pesquisando"], variable=f"{p}_priority"),
        _node(f"{p}_score", "action", "Calcular score", action="set_variables", fields={f"{p}_score": "{{score}}"}),
        _node(f"{p}_tag", "action", "Aplicar tag operacional", action="add_tag", tag=f"{segment}:{key}"),
        _node(f"{p}_crm", "action", "Atualizar CRM", action="update_contact", fields={"interest": f"{{{{{p}_intent}}}}", "priority": f"{{{{{p}_priority}}}}"}),
        _node(f"{p}_pipeline", "action", "Mover no pipeline", action="move_pipeline", stage="Qualificado"),
        _node(f"{p}_confirm", "message", "Confirmar próxima ação", content="Perfeito. Registrei tudo e vou conduzir a próxima etapa."),
        _node(f"{p}_wait", "delay", "Janela de acompanhamento", duration=30, unit="minutes"),
        _node(f"{p}_followup", "message", "Follow-up contextual", content="Conseguiu avançar? Responda CONTINUAR ou HUMANO."),
        _node(f"{p}_fallback", "message", "Fallback orientado", content="Não consegui identificar a opção. Escolha uma alternativa do menu."),
        _node(f"{p}_human", "action", "Transferência humana", action="human_handoff", queue=segment, include_context=True),
        _node(f"{p}_end", "message", "Encerramento", content="Atendimento registrado. Conte conosco!"),
    ]
    if ai:
        nodes.insert(5, _node(f"{p}_ai", ai, "Classificação assistida por IA", classes=["success", "fallback", "human"], fallback="human"))
    if integration:
        nodes.insert(-5, _node(f"{p}_integration", "action", f"Integração {integration}", action=integration, operation="create_or_update"))
    route = f"{p}_route"; qualify = f"{p}_qualify"; ai_key = f"{p}_ai"
    edges = [("start", f"{p}_welcome", None), (f"{p}_welcome", f"{p}_identify", None), (f"{p}_identify", f"{p}_capture", None), (f"{p}_capture", route, None)]
    edges += [(route, ai_key if ai else qualify, "success"), (route, f"{p}_fallback", "fallback"), (route, f"{p}_human", "human")]
    if ai: edges += [(ai_key, qualify, "success"), (ai_key, f"{p}_human", "human")]
    chain = [qualify, f"{p}_score", f"{p}_tag", f"{p}_crm", f"{p}_pipeline"]
    if integration: chain.append(f"{p}_integration")
    chain += [f"{p}_confirm", f"{p}_wait", f"{p}_followup", f"{p}_end"]
    edges += [(chain[i], chain[i + 1], None) for i in range(len(chain) - 1)]
    edges += [(f"{p}_fallback", f"{p}_identify", "retry"), (f"{p}_fallback", f"{p}_human", "human"), (f"{p}_human", f"{p}_end", None)]
    return _asset(key, name, "hybrid" if ai else "no_ai", nodes, edges, segment=segment, integrations=(integration,) if integration else ())


def _initial_menu_graph() -> dict[str, Any]:
    """Reference contact-centre flow, positioned by hand for the Flow Builder."""
    options = [
        {"id": "atendimento", "label": "Atendimento"},
        {"id": "comercial", "label": "Comercial"},
        {"id": "financeiro", "label": "Financeiro"},
        {"id": "agendamento", "label": "Agendamento"},
        {"id": "faq", "label": "Perguntas frequentes"},
        {"id": "humano", "label": "Falar com uma pessoa"},
    ]
    nodes = [
        _node("start", "start", "Início do atendimento"),
        _node("menu_welcome", "message", "Mensagem de boas-vindas", content="Olá, {{contact.name}}! Boas-vindas à nossa central de atendimento."),
        _node("menu_context", "action", "Preparar contexto do contato", action="set_variables", fields={"customer_name": "{{contact.name}}", "service_origin": "menu_inicial"}),
        _node("menu_prompt", "message", "Menu principal", content="Como podemos ajudar? Escolha uma das opções abaixo."),
        _node("menu_router", "choice", "Router principal", options=options, variable="service_route"),
    ]
    branches = [
        ("atendimento", "Atendimento", "Entendi. Vou encaminhar sua solicitação para a equipe de atendimento.", "atendimento"),
        ("comercial", "Comercial", "Ótimo! Nossa equipe comercial vai continuar com você.", "comercial"),
        ("financeiro", "Financeiro", "Certo. Vou direcionar sua solicitação para o financeiro.", "financeiro"),
        ("agendamento", "Agendamento", "Vamos cuidar do seu agendamento com uma pessoa da equipe.", "agendamento"),
        ("faq", "FAQ", "Vou encaminhar sua dúvida para que você receba uma resposta confiável.", "faq"),
        ("humano", "Atendimento humano", "Claro. Vou chamar uma pessoa para continuar o atendimento.", "atendimento_humano"),
    ]
    for key, label, content, queue in branches:
        nodes.extend([
            _node(f"menu_{key}_message", "message", f"Orientação · {label}", content=content),
            _node(f"menu_{key}_route", "action", f"Registrar rota · {label}", action="set_variables", fields={"service_route": key, "service_queue": queue}),
        ])
    nodes.extend([
        _node("menu_handoff", "action", "Transferência humana", action="human_handoff", queue="{{service_queue}}", include_context=True),
        _node("menu_end", "message", "Encerramento", content="Pronto! Seu atendimento foi encaminhado. Nossa equipe continuará por aqui."),
    ])

    edges = [
        ("start", "menu_welcome", None),
        ("menu_welcome", "menu_context", None),
        ("menu_context", "menu_prompt", None),
        ("menu_prompt", "menu_router", None),
    ]
    for key, *_ in branches:
        edges.extend([
            ("menu_router", f"menu_{key}_message", key),
            (f"menu_{key}_message", f"menu_{key}_route", None),
            (f"menu_{key}_route", "menu_handoff", None),
        ])
    edges.append(("menu_handoff", "menu_end", None))

    asset = _asset("menu_inicial", "Menu inicial", "no_ai", nodes, edges)
    positions = {
        "start": (900, 40), "menu_welcome": (900, 220), "menu_context": (900, 400),
        "menu_prompt": (900, 580), "menu_router": (900, 760),
        "menu_handoff": (900, 1340), "menu_end": (900, 1520),
    }
    branch_x = {key: index * 360 for index, (key, *_rest) in enumerate(branches)}
    for key, x in branch_x.items():
        positions[f"menu_{key}_message"] = (x, 980)
        positions[f"menu_{key}_route"] = (x, 1160)
    for node in asset["graph"]["nodes"]:
        x, y = positions[node["key"]]
        node["position"] = {"x": x, "y": y}
    asset["description"] = "Central de atendimento com seis rotas explícitas, handoff contextual e encerramento único."
    asset["metadata"].update({"architecture": "reference_contact_centre_v2", "layout": "manual", "branch_count": len(branches)})
    return asset


NO_AI = {
    "menu_inicial": ("Menu inicial", "Escolha Atendimento, Comercial, Financeiro, Agendamento ou FAQ."),
    "atendimento_por_setor": ("Atendimento por setor", "Identifique seu setor e informe o assunto."),
    "qualificacao_de_lead": ("Qualificação de lead", "Vamos registrar nome, empresa, cidade, interesse, orçamento e urgência."),
    "agendamento_simples": ("Agendamento simples", "Escolha serviço, profissional, data e horário."),
    "follow_up": ("Follow-up", "Vamos retomar sua conversa do ponto em que parou."),
    "pesquisa_nps": ("Pesquisa NPS", "Dê uma nota de 0 a 10; detratores geram tarefa imediata."),
    "cobranca": ("Cobrança", "Consulte a pendência e escolha PIX, boleto ou financeiro."),
    "transferencia_humana": ("Transferência humana", "Sua conversa será entregue com todo o contexto."),
    "faq_estruturado": ("FAQ estruturado", "Escolha categoria e subcategoria para uma resposta determinística."),
    "coleta_de_dados": ("Coleta de dados", "Confirme seus dados com validação e possibilidade de correção."),
}
HYBRID = {"atendimento_com_fallback_para_ia": "Atendimento com fallback para IA", "qualificacao_inteligente": "Qualificação inteligente", "agendamento_hibrido": "Agendamento híbrido", "faq_com_rag": "FAQ com RAG", "crm_assistido_por_ia": "CRM assistido por IA", "comercial_com_handoff": "Comercial com handoff", "recuperacao_de_lead_com_ia": "Recuperação de lead com IA"}

ASSETS = {key: _operational_graph(key, name, objective) for key, (name, objective) in NO_AI.items()}
ASSETS["menu_inicial"] = _initial_menu_graph()
for key, name in HYBRID.items():
    ASSETS[key] = _operational_graph(key, name, "A IA classifica apenas a intenção; regras e pessoas controlam a operação.", ai="ai_rag" if key == "faq_com_rag" else "ai_classification")
for key, name, focus, integration in [("agenda_inteligente", "Agenda Inteligente", "agendamento", "google_calendar"), ("atendimento_inteligente", "Atendimento Inteligente", "atendimento", None), ("comercial_inteligente", "Comercial Inteligente", "comercial", None)]:
    ASSETS[key] = _operational_graph(key, name, f"Contextualize e classifique {focus} com segurança.", ai="ai_rag", integration=integration)
    ASSETS[key]["metadata"]["automation_level"] = "full_ai"; ASSETS[key]["supported_variants"] = ["full_ai"]

KIT_DOMAINS = {
    "clinica_odontologica": ("odontologia", ["Menu Principal", "Primeira Consulta", "Emergência", "Avaliação", "Orçamento", "Confirmação", "Reagendamento", "Cancelamento", "Pós Consulta", "Pesquisa", "Recuperação", "Financeiro"], "paciente, especialidade, convênio e dor"),
    "imobiliaria": ("imobiliaria", ["Recepção", "Compra", "Locação", "Captação de imóvel", "Qualificação financeira", "Visita", "Proposta", "Documentação", "Follow-up", "Pós-visita", "Proprietário", "Handoff corretor"], "comprador, bairro, quartos e faixa de preço"),
    "restaurante": ("restaurante", ["Recepção", "Cardápio", "Delivery", "Retirada", "Reserva", "Restrições alimentares", "Pagamento", "Status do pedido", "Avaliação", "Recuperação", "Fidelidade", "Gerente"], "pedido, itens, endereço e forma de pagamento"),
    "advocacia": ("advocacia", ["Recepção", "Conflito de interesse", "Área jurídica", "Urgência", "Documentos", "Triagem", "Consulta", "Confirmação", "Andamento", "Financeiro", "Pesquisa", "Handoff advogado"], "parte, área jurídica, prazo e documentos"),
}
for kit, (segment, flow_names, vocabulary) in KIT_DOMAINS.items():
    for order, flow_name in enumerate(flow_names, 1):
        asset_key = f"{segment}_{order:02d}_{flow_name.lower().replace(' ', '_').replace('ç', 'c').replace('ã', 'a').replace('ê', 'e').replace('ó', 'o')}"
        ASSETS[asset_key] = _operational_graph(asset_key, f"{order:02d} · {flow_name} · {segment.title()}", f"Operação especializada: colete {vocabulary} para {flow_name.lower()}.", segment=segment)

ITEMS: dict[str, dict[str, Any]] = {}
for key in [*NO_AI, *HYBRID, "agenda_inteligente", "atendimento_inteligente", "comercial_inteligente"]:
    kind = "flow_template" if key in NO_AI else "hybrid_flow" if key in HYBRID else "ai_system"
    ITEMS[key] = {"key": key, "version": "2.0.0", "template_type": kind, "availability": "installable_real", "variants": ASSETS[key]["supported_variants"], "flow_assets": [key]}
for kit, (segment, _, _) in KIT_DOMAINS.items():
    ITEMS[kit] = {"key": kit, "version": "2.0.0", "template_type": "business_kit", "availability": "installable_real", "variants": ["no_ai"] if kit != "clinica_odontologica" else ["no_ai", "hybrid", "full_ai"], "flow_assets": [key for key, asset in ASSETS.items() if asset["metadata"]["segment"] == segment], "pipeline": f"{segment}_pipeline@2.0.0"}


def get_asset(key: str) -> dict[str, Any]:
    if key not in ASSETS: raise LookupError("asset_not_found")
    return deepcopy(ASSETS[key])


def get_item(key: str) -> dict[str, Any]:
    if key not in ITEMS: raise LookupError("template_not_found")
    return deepcopy(ITEMS[key])
