"""Canonical, user-facing validation for Flow Builder graphs.

This module deliberately has no runtime dependencies.  It validates the editor
snapshot only; Runtime V2 remains unchanged.
"""
from __future__ import annotations

from typing import Any


MESSAGES = {
    "START_MISSING": ("Defina um node inicial.", "Marque um node como início do fluxo."),
    "MULTIPLE_STARTS": ("O fluxo deve ter apenas um node inicial.", "Mantenha apenas um node marcado como início."),
    "MESSAGE_EMPTY": ("Adicione o conteúdo da mensagem.", "Abra o node e escreva a mensagem."),
    "MESSAGE_REQUIRES_OUTPUT": ("Conecte esta mensagem a outro node ou marque-a como fim do fluxo.", "Conecte uma saída ou marque como fim do fluxo."),
    "CONDITION_EMPTY": ("Adicione pelo menos uma regra.", "Abra o node e configure pelo menos uma condição."),
    "CONDITION_INCOMPLETE": ("Preencha campo, operador e valor.", "Complete todos os campos da regra."),
    "CONDITION_NEEDS_BOTH_BRANCHES": ("Conecte as saídas Sim e Não.", "Ligue as duas saídas a nodes de destino."),
    "CHOICE_EMPTY": ("Adicione pelo menos uma opção.", "Abra o node e adicione uma opção."),
    "CHOICE_OPTION_EMPTY": ("Preencha o nome da opção.", "Informe um nome para cada opção."),
    "CHOICE_OPTION_WITHOUT_TARGET": ("A opção não está conectada a nenhum node.", "Conecte a opção a um node de destino."),
    "CHOICE_DUPLICATE_HANDLE": ("Existem opções com identificadores duplicados.", "Use um identificador diferente em cada opção."),
    "AI_INSTRUCTION_EMPTY": ("Adicione uma instrução para a IA.", "Abra o node e descreva a tarefa da IA."),
    "AI_OUTPUT_VARIABLE_EMPTY": ("Defina a variável de saída.", "Informe onde a resposta da IA será armazenada."),
    "AI_CATEGORIES_EMPTY": ("Adicione pelo menos uma categoria.", "Cadastre uma categoria de classificação."),
    "ACTION_TYPE_EMPTY": ("Selecione uma ação.", "Abra o node e selecione a ação desejada."),
    "ACTION_CONFIG_INCOMPLETE": ("Complete os parâmetros obrigatórios da ação.", "Preencha os campos obrigatórios destacados."),
    "NODE_ORPHAN": ("Este node não está conectado ao caminho iniciado pelo Start.", "Conecte o node ao caminho iniciado pelo Start."),
    "EDGE_INVALID": ("Existe uma conexão inválida entre nodes.", "Remova a conexão inválida e conecte os nodes novamente."),
    "DATA_COLLECTION_INVALID": ("Revise a configuração da Coleta de Dados.", "Preencha os campos destacados e conecte as saídas necessárias."),
}


def _issue(code: str, node: dict[str, Any] | None = None, *, field: str | None = None, message: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    node = node or {}
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    default_message, suggestion = MESSAGES[code]
    node_type = str(node.get("type") or data.get("type") or "flow").lower()
    label = str(data.get("label") or data.get("title") or node_type.replace("_", " ").title())
    return {
        "code": code, "message": message or default_message,
        "summary": f'O node {label} está incompleto.' if node else "O fluxo está incompleto.",
        "node_id": str(node.get("id")) if node.get("id") else None,
        "node_type": node_type if node else None, "node_label": label if node else None,
        "field": field, "focus_field": field, "severity": "error",
        "suggestion": suggestion, "metadata": metadata or {}, "details": metadata or {},
    }


def validate_builder_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every actionable issue in a builder snapshot."""
    issues: list[dict[str, Any]] = []
    valid_nodes = [n for n in nodes if isinstance(n, dict)]
    by_id = {str(n.get("id")): n for n in valid_nodes if n.get("id")}
    starts = [n for n in valid_nodes if bool((n.get("data") or {}).get("isStart"))]
    if not starts: issues.append(_issue("START_MISSING"))
    elif len(starts) > 1: issues.append(_issue("MULTIPLE_STARTS"))
    outgoing: dict[str, list[dict[str, Any]]] = {key: [] for key in by_id}
    incoming: dict[str, list[dict[str, Any]]] = {key: [] for key in by_id}
    for edge in edges or []:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source not in by_id or target not in by_id:
            issues.append(_issue("EDGE_INVALID", by_id.get(source) or by_id.get(target), field="connections", metadata={"edge_id": edge.get("id")})); continue
        outgoing[source].append(edge); incoming[target].append(edge)
    reachable: set[str] = set()
    pending = [str(starts[0].get("id"))] if len(starts) == 1 else []
    while pending:
        current = pending.pop()
        if current in reachable: continue
        reachable.add(current); pending.extend(str(e.get("target")) for e in outgoing.get(current, []))
    for node_id, node in by_id.items():
        data = node.get("data") or {}; kind = str(node.get("type") or data.get("type") or "").lower()
        if starts and node_id not in reachable: issues.append(_issue("NODE_ORPHAN", node, field="connections"))
        terminal = any(bool(data.get(k)) for k in ("is_terminal", "isEnd", "isFinal", "endFlow"))
        if kind in {"message", "start"}:
            content = data.get("content") or data.get("text") or data.get("message")
            if not str(content or "").strip(): issues.append(_issue("MESSAGE_EMPTY", node, field="content"))
            if not outgoing[node_id] and not terminal: issues.append(_issue("MESSAGE_REQUIRES_OUTPUT", node, field="connections"))
        elif kind == "condition":
            rules = node.get("conditions") or data.get("conditions") or data.get("rules")
            if not isinstance(rules, list) or not rules: issues.append(_issue("CONDITION_EMPTY", node, field="conditions"))
            elif any(not isinstance(r, dict) or not str(r.get("field") or r.get("left") or r.get("path") or "").strip() or not str(r.get("operator") or r.get("op") or "").strip() or (r.get("value") if "value" in r else r.get("right")) in (None, "") for r in rules): issues.append(_issue("CONDITION_INCOMPLETE", node, field="conditions"))
            handles = {str(e.get("sourceHandle") or (e.get("data") or {}).get("sourceHandle") or "").lower() for e in outgoing[node_id]}
            if not {"true", "false"}.issubset(handles): issues.append(_issue("CONDITION_NEEDS_BOTH_BRANCHES", node, field="connections"))
        elif kind == "choice":
            options = data.get("options") or data.get("buttons") or node.get("options")
            if not isinstance(options, list) or not options: issues.append(_issue("CHOICE_EMPTY", node, field="options")); continue
            handles = []
            edge_handles = {str(e.get("sourceHandle") or (e.get("data") or {}).get("sourceHandle") or "") for e in outgoing[node_id]}
            for index, option in enumerate(options):
                option = option if isinstance(option, dict) else {}; label = str(option.get("label") or option.get("name") or "").strip(); handle = str(option.get("handleId") or option.get("handle_id") or option.get("id") or option.get("value") or "")
                if not label: issues.append(_issue("CHOICE_OPTION_EMPTY", node, field=f"options.{index}.label"))
                if handle not in edge_handles: issues.append(_issue("CHOICE_OPTION_WITHOUT_TARGET", node, field=f"options.{index}", message=f"A opção ‘{label or index + 1}’ não está conectada a nenhum node."))
                handles.append(handle)
            if len(handles) != len(set(handles)): issues.append(_issue("CHOICE_DUPLICATE_HANDLE", node, field="options"))
        elif kind == "data_collection":
            variable = str(data.get("variable_name") or "")
            if not variable: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="variable_name", message="Defina o nome da variável."))
            elif not __import__("re").fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", variable): issues.append(_issue("DATA_COLLECTION_INVALID", node, field="variable_name", message="Use letras, números e underscore; não comece com número."))
            if str(data.get("data_type") or "") not in {"text", "number", "email", "phone", "date", "time", "cpf", "cnpj", "url", "currency", "boolean", "choice"}: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="data_type", message="Selecione um tipo de dado válido."))
            if int(data.get("max_attempts") or 0) < 1: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="max_attempts", message="O máximo de tentativas deve ser maior que zero."))
            if int(data.get("timeout_seconds") or 0) < 0: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="timeout_seconds", message="O timeout não pode ser negativo."))
            options = data.get("options") or []
            if data.get("data_type") == "choice" and not options: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="options", message="Adicione pelo menos uma opção."))
            ids = [str(option.get("id") or "") for option in options if isinstance(option, dict)]; values = [str(option.get("value") or "") for option in options if isinstance(option, dict)]
            if any(not value for value in ids): issues.append(_issue("DATA_COLLECTION_INVALID", node, field="options", message="Todas as opções precisam de um identificador."))
            if len(ids) != len(set(ids)) or len(values) != len(set(values)): issues.append(_issue("DATA_COLLECTION_INVALID", node, field="options", message="IDs e valores das opções devem ser únicos."))
            handles = {str(edge.get("sourceHandle") or "") for edge in outgoing[node_id]}
            if "success" not in handles: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="connections", message="A saída Sucesso precisa estar conectada."))
            if int(data.get("timeout_seconds") or 0) > 0 and "timeout" not in handles: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="connections", message="Conecte a saída Timeout."))
            if data.get("cancel_keywords") and "cancel" not in handles: issues.append(_issue("DATA_COLLECTION_INVALID", node, field="connections", message="Conecte a saída Cancelar."))
            follows_invalid = data.get("auto_retry_invalid") is not True or data.get("attempts_exceeded_behavior", "invalid") == "invalid"
            if follows_invalid and "invalid" not in handles:
                message = "Conecte a saída Tentativas esgotadas ou selecione Encerrar após exceder tentativas." if data.get("auto_retry_invalid") is True else "Conecte a saída Inválido."
                issues.append(_issue("DATA_COLLECTION_INVALID", node, field="connections", message=message))
    return issues
