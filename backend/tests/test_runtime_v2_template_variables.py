import logging
from types import SimpleNamespace

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.template_renderer import FlowRenderContext, render_template
from app.flow_v2.executors._legacy import (
    ActionNodeExecutor,
    AiClassificationNodeExecutor,
    ConditionNodeExecutor,
    MessageNodeExecutor,
)
from app.flow_v2.executors.data_collection_executor import RuntimeV2DataCollectionExecutor


def context(*, variables=None, legacy=None):
    session = SimpleNamespace(id="session-1", variables=variables or {}, context=legacy or {})
    return FlowRenderContext(tenant_id="tenant-1", session=session, node_id="message-1")


def test_renders_persisted_data_collection_and_classification_variables():
    render_context = context(variables={"treatment_request": "Limpeza", "intent_category": "Implante"})
    assert render_template("Você informou {{treatment_request}}", render_context) == "Você informou Limpeza"
    assert render_template("Categoria: {{intent_category}}", render_context) == "Categoria: Implante"


def test_supports_variables_namespace_dot_notation_and_legacy_braces():
    render_context = context(variables={"intent_category": "Limpeza", "customer": {"period": "manhã"}})
    assert render_template("{{variables.intent_category}} / {{customer.period}} / {intent_category}", render_context) == "Limpeza / manhã / Limpeza"


def test_persisted_variables_survive_reloaded_session_and_override_legacy_context():
    session = SimpleNamespace(id="reloaded", variables={"intent_category": "Limpeza"}, context={"intent_category": "Legado"})
    template = "Identifiquei que você procura um tratamento de {{intent_category}}."
    assert render_template(template, FlowRenderContext(tenant_id="tenant-1", session=session)) == "Identifiquei que você procura um tratamento de Limpeza."


def test_missing_placeholder_is_empty_and_emits_structured_log(caplog):
    with caplog.at_level("WARNING"):
        rendered = render_template("Valor: {{missing_variable}}", context())
    assert rendered == "Valor: "
    assert "event=runtime_v2_template_render" in caplog.text
    assert "missing_keys=['missing_variable']" in caplog.text
    assert "node_id=message-1" in caplog.text


def test_ai_classification_persists_configured_output_in_variables():
    session = SimpleNamespace(context={}, variables={})
    executor = object.__new__(AiClassificationNodeExecutor)

    executor._save_result(SimpleNamespace(), session=session, output_variable="intent_category", result={"category": "Limpeza", "confidence": 0.94})

    assert session.variables["intent_category"] == "Limpeza"
    assert session.context["intent_category"] == "Limpeza"


def test_data_collection_classification_condition_message_interpolates_output(
    monkeypatch, caplog
):
    """Regression for the real Runtime V2 node sequence reported in production."""
    routes = {
        ("collection", "success"): "classification",
        ("classification", None): "condition",
        ("condition", "true"): "message",
    }

    class Resolver:
        def resolve(self, _db, *, source_node_id, source_handle=None, **_kwargs):
            target = routes[(source_node_id, source_handle)]
            return SimpleNamespace(target_node_id=target, edge={"id": f"{source_node_id}-{target}"})

    class EventStore:
        def append(self, *_args, **_kwargs):
            return None

    session = SimpleNamespace(
        id="session-flow",
        tenant_id="tenant-1",
        flow_version_id="version-1",
        context={
            "waiting_for": "data_collection",
            "waiting_node_id": "collection",
            "data_collection": {
                "attempts": 0,
                "max_attempts": 1,
                "processed_message_ids": [],
                "retry_mode": False,
            },
        },
        variables={},
    )
    nodes = {
        "collection": {"id": "collection", "type": "data_collection", "data": {"variable_name": "treatment_request", "data_type": "text"}},
        "classification": {"id": "classification", "type": "ai_classification", "data": {"input_template": "{{treatment_request}}", "categories": ["Implante", "Limpeza"], "confidence_threshold": 0.6, "output_variable": "intent_category"}},
        "condition": {"id": "condition", "type": "condition", "data": {"conditions": [{"field": "intent_category", "operator": "equals", "value": "Implante"}]}},
        "message": {"id": "message", "type": "message", "content": "Categoria classificada: {{intent_category}}"},
    }
    snapshot = SimpleNamespace(
        node_by_id=nodes,
        transitions=tuple(
            {"source_node_id": source, "source_handle": handle, "target_node_id": target}
            for (source, handle), target in routes.items()
        ),
        edges=(),
        start_node_id="collection",
        flow_id="flow-1",
        name="Regression flow",
    )
    runtime_input = RuntimeInput(
        tenant_id="tenant-1",
        flow_version_id="version-1",
        external_user_id="whatsapp:+5511999999999",
        message_text="Quero colocar um implante",
        input_message_id="input-1",
        metadata={},
    )
    db = SimpleNamespace(add=lambda _value: None)
    event_store, resolver = EventStore(), Resolver()

    monkeypatch.setattr("app.flow_v2.executors._legacy.resolve_ai_config", lambda *_args: {})
    monkeypatch.setattr("app.flow_v2.executors._legacy.classify_for_tenant", lambda *_args, **_kwargs: {"category": "Implante", "confidence": 0.98, "reason": "pedido explícito"})
    monkeypatch.setattr("app.flow_v2.executors._legacy.record_ai_execution", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.flow_v2.executors._legacy.get_flow_id", lambda *_args, **_kwargs: "flow-1")
    monkeypatch.setattr(ActionNodeExecutor, "_resolve_contact", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(ActionNodeExecutor, "_resolve_conversation", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(ActionNodeExecutor, "_resolve_lead", staticmethod(lambda *_args, **_kwargs: None))

    collection = RuntimeV2DataCollectionExecutor(event_store=event_store, transition_resolver=resolver)
    classification = AiClassificationNodeExecutor(event_store=event_store, transition_resolver=resolver)
    condition = ConditionNodeExecutor(event_store=event_store, transition_resolver=resolver)
    message = MessageNodeExecutor(event_store=event_store, transition_resolver=resolver)

    with caplog.at_level(logging.INFO):
        assert collection.execute(db, snapshot=snapshot, session=session, node=nodes["collection"], runtime_input=runtime_input).next_node_id == "classification"
        assert classification.execute(db, snapshot=snapshot, session=session, node=nodes["classification"], runtime_input=runtime_input).next_node_id == "condition"
        assert session.variables["intent_category"] == "Implante"
        assert condition.execute(db, snapshot=snapshot, session=session, node=nodes["condition"], runtime_input=runtime_input).next_node_id == "message"
        result = message.execute(db, snapshot=snapshot, session=session, node=nodes["message"], runtime_input=runtime_input)

    assert result.actions[0].text == "Categoria classificada: Implante"
    assert "{{intent_category}}" not in result.actions[0].text
    assert "output_variable=intent_category" in caplog.text
    assert "session.variables={'treatment_request': 'Quero colocar um implante', 'intent_category': 'Implante'}" in caplog.text
    assert "resolved_keys=['intent_category'] missing_keys=[]" in caplog.text
