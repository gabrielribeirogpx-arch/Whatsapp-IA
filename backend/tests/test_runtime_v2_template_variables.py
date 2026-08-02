from types import SimpleNamespace

from app.flow_v2.template_renderer import FlowRenderContext, render_template
from app.flow_v2.executors._legacy import AiClassificationNodeExecutor


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
