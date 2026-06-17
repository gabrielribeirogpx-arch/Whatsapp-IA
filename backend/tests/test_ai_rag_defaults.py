from __future__ import annotations

import uuid

from app.services.embedding_service import cosine_similarity
from app.services import llm_service


class _EmptyResult:
    def scalars(self):
        return self

    def first(self):
        return None


class _EmptyDB:
    def execute(self, statement):
        return _EmptyResult()


def test_resolve_tenant_config_uses_defaults_when_rag_options_are_none(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("AI_TEMPERATURE", raising=False)
    monkeypatch.delenv("AI_MAX_TOKENS", raising=False)

    config = llm_service._resolve_tenant_config(
        _EmptyDB(),
        uuid.uuid4(),
        options={"temperature": None, "max_tokens": None},
    )

    assert config["temperature"] == llm_service.DEFAULT_TEMPERATURE
    assert config["max_tokens"] == llm_service.DEFAULT_MAX_TOKENS


def test_cosine_similarity_treats_none_vector_values_as_zero():
    assert cosine_similarity([None, 1.0], [1.0, 1.0]) > 0


def test_rag_context_omits_source_labels_by_default():
    from app.services.rag_service import _format_context_for_prompt

    contexts = [
        {
            "source_name": "EDITAL_2026.pdf",
            "content": "Prazo de inscrição até 30 de junho.",
            "metadata": {"page": 4},
        }
    ]

    prompt_context = _format_context_for_prompt(contexts)

    assert "Prazo de inscrição" in prompt_context
    assert "Fonte:" not in prompt_context
    assert "EDITAL_2026" not in prompt_context
    assert "página" not in prompt_context.lower()


def test_rag_context_can_include_source_labels_when_enabled():
    from app.services.rag_service import _format_context_for_prompt

    contexts = [
        {
            "source_name": "EDITAL_2026.pdf",
            "content": "Prazo de inscrição até 30 de junho.",
            "metadata": {"page": 4},
        }
    ]

    prompt_context = _format_context_for_prompt(contexts, include_sources=True)

    assert "Fonte: EDITAL_2026.pdf, página 4" in prompt_context
    assert "Prazo de inscrição" in prompt_context


def test_rag_prompt_uses_whatsapp_short_style_by_default(monkeypatch):
    from app.services import rag_service

    captured = {}

    monkeypatch.setattr(
        rag_service,
        "retrieve_context",
        lambda db, tenant_id, question, top_k: [
            {
                "source_name": "lista_docs.pdf",
                "content": "Documentos necessários: RG, CPF e comprovante de residência.",
                "metadata": {"page": 2},
            }
        ],
    )

    def fake_generate(db, tenant_id, messages, options=None):
        captured["messages"] = messages
        return "Leve estes documentos:\n\n• RG\n• CPF\n• comprovante de residência"

    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", fake_generate)

    answer = rag_service.answer_with_rag(None, uuid.uuid4(), "Quais documentos preciso levar?")

    system_prompt = captured["messages"][0]["content"]
    user_prompt = captured["messages"][1]["content"]
    assert answer.answer.startswith("Leve estes documentos")
    assert "FORMATO DA RESPOSTA NO WHATSAPP" in system_prompt
    assert "Responda em português do Brasil como atendente de WhatsApp." in system_prompt
    assert "Seja direto, natural e útil." in system_prompt
    assert "Use no máximo 2 a 4 parágrafos curtos." in system_prompt
    assert "Use bullets só quando eles deixarem a resposta mais fácil de ler." in system_prompt
    assert "Não cite Fonte, arquivo, página ou chunk." in system_prompt
    assert "Fonte:" not in user_prompt
    assert "lista_docs.pdf" not in user_prompt
    assert "página" not in user_prompt.lower()


def test_rag_prompt_uses_human_fallback_by_default(monkeypatch):
    from app.services import rag_service

    monkeypatch.setattr(rag_service, "retrieve_context", lambda *args, **kwargs: [])
    answer = rag_service.answer_with_rag(None, uuid.uuid4(), "tem estacionamento?")

    assert answer.answer == "Não encontrei essa informação com segurança na base disponível. Quer que eu encaminhe para um atendente?"
    assert answer.found_context is False


def test_rag_includes_sources_only_when_question_asks_for_source(monkeypatch):
    from app.services import rag_service

    captured = {}
    context = [
        {
            "source_name": "edital.pdf",
            "content": "A inscrição encerra em 30 de junho.",
            "metadata": {"page": 4},
        }
    ]
    monkeypatch.setattr(rag_service, "retrieve_context", lambda db, tenant_id, question, top_k: context)

    def fake_generate(db, tenant_id, messages, options=None):
        captured["messages"] = messages
        return "Está no edital, página 4."

    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", fake_generate)

    rag_service.answer_with_rag(None, uuid.uuid4(), "De onde tirou?")

    user_prompt = captured["messages"][1]["content"]
    assert "Fonte: edital.pdf, página 4" in user_prompt


def test_ai_rag_prompt_receives_history(monkeypatch):
    from app.services import rag_service

    captured = {}
    monkeypatch.setattr(rag_service, "retrieve_context", lambda db, tenant_id, question, top_k: [{"content": "E-mail: contato@example.com", "metadata": {}, "source_name": "kb"}])

    def fake_generate(db, tenant_id, messages, options=None):
        captured["user_prompt"] = messages[1]["content"]
        return "O e-mail é contato@example.com"

    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", fake_generate)

    rag_service.answer_with_rag(None, uuid.uuid4(), "e o e-mail?", conversation_context="Usuário: Quero atendimento\nAssistente: Claro.")

    assert "HISTÓRICO RECENTE DA CONVERSA" in captured["user_prompt"]
    assert "Usuário: Quero atendimento" in captured["user_prompt"]
    assert "PERGUNTA ATUAL:\ne o e-mail?" in captured["user_prompt"]


def test_ai_rag_does_not_greet_again_when_history_exists(monkeypatch):
    from app.services import rag_service

    captured = {}
    monkeypatch.setattr(rag_service, "retrieve_context", lambda db, tenant_id, question, top_k: [{"content": "Prazo: 5 dias úteis", "metadata": {}, "source_name": "kb"}])
    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", lambda db, tenant_id, messages, options=None: captured.setdefault("system_prompt", messages[0]["content"]) or "5 dias úteis")

    rag_service.answer_with_rag(None, uuid.uuid4(), "e o prazo?", conversation_context="Assistente: Olá!", is_first_ai_turn=False)

    assert "Esta conversa já está em andamento. Não cumprimente novamente." in captured["system_prompt"]
    assert 'Não repita "Olá" se já houver mensagem anterior do assistente no histórico.' in captured["system_prompt"]


def test_ai_rag_internal_placeholders_do_not_go_through_flow_template(caplog, monkeypatch):
    from types import SimpleNamespace
    from app.flow_v2.contracts import RuntimeInput
    from app.flow_v2.node_executors import AiRagNodeExecutor
    from app.flow_v2.snapshot import FlowV2Snapshot
    from app.services import rag_service
    import app.flow_v2.node_executors as node_executors

    class EventStore:
        def append(self, *args, **kwargs):
            pass

    class Resolver:
        pass

    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    session_id = uuid.uuid4()
    node_id = str(uuid.uuid4())
    snapshot = FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash="h",
        nodes=(
            {
                "id": node_id,
                "type": "ai_rag",
                "data": {
                    "instruction": "{{assistant_instruction}}\nUse a base.",
                    "question": "{{last_message}} {{history}}",
                    "fallback_message": "{{chunks}}Não achei.",
                    "after_answer_behavior": "end_flow",
                    "memory_enabled": False,
                },
            },
        ),
        edges=(),
        start_node_id=node_id,
    )
    session = SimpleNamespace(id=session_id, tenant_id=tenant_id, flow_version_id=flow_version_id)
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=flow_version_id, external_user_id="whatsapp:+55", message_text="me fale do edital", metadata={"message_id": "m1"})
    captured = {}

    def fake_answer(*args, **kwargs):
        captured.update(kwargs)
        return rag_service.RagAnswer(answer="Resumo do edital", contexts=[], found_context=True)

    monkeypatch.setattr(node_executors, "answer_with_rag", fake_answer)

    with caplog.at_level("WARNING"):
        AiRagNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(None, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "unknown placeholder" not in log_text
    assert "assistant_instruction" not in log_text
    assert "chunks" not in log_text
    assert "history" not in log_text
    assert captured["system_policy"] == "Use a base."


def test_ai_rag_wait_same_node_reuses_memory(monkeypatch):
    from types import SimpleNamespace
    from app.flow_v2.contracts import RuntimeInput
    from app.flow_v2.node_executors import AiRagNodeExecutor
    from app.flow_v2.snapshot import FlowV2Snapshot
    from app.services import rag_service
    import app.flow_v2.node_executors as node_executors

    calls = {"user": 0, "assistant": 0, "history": 0}

    class Memory:
        def append_user_message(self, *args, **kwargs):
            calls["user"] += 1
        def append_assistant_message(self, *args, **kwargs):
            calls["assistant"] += 1
        def get_recent_history(self, *args, **kwargs):
            calls["history"] += 1
            return [SimpleNamespace(role="user", content="Quero prazo")]
        def build_history_for_prompt(self, messages):
            return "Usuário: Quero prazo"

    class EventStore:
        def append(self, *args, **kwargs):
            pass

    class Resolver:
        pass

    class DB:
        def get(self, model, item_id):
            return SimpleNamespace(flow_id=flow_id)

    flow_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    session_id = uuid.uuid4()
    node_id = str(uuid.uuid4())
    snapshot = FlowV2Snapshot(flow_version_id=flow_version_id, tenant_id=tenant_id, hash="h", nodes=({"id": node_id, "type": "ai_rag", "data": {"after_answer_behavior": "wait_same_node"}},), edges=(), start_node_id=node_id)
    session = SimpleNamespace(id=session_id, tenant_id=tenant_id, flow_version_id=flow_version_id)
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=flow_version_id, external_user_id="whatsapp:+55", message_text="e o prazo?", metadata={"message_id": "m1"})

    monkeypatch.setattr(node_executors, "flow_ai_memory_service", Memory())
    monkeypatch.setattr(node_executors, "answer_with_rag", lambda *args, **kwargs: rag_service.RagAnswer(answer="5 dias úteis", contexts=[], found_context=True))

    result = AiRagNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(DB(), snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.status == "wait"
    assert result.next_node_id == node_id
    assert calls == {"user": 1, "assistant": 1, "history": 1}
