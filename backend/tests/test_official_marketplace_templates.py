import pytest

from app.flow_v2.publisher import FlowV2Publisher
from app.flow_v2.node_handle_contract import migrate_edge_handles
from app.services.official_marketplace_template_service import publication_boundary_edges, remap_graph, sanitize_snapshot, structural_diff


def graph():
    nodes = [
        {"id": "start", "type": "choice", "position": {"x": 1, "y": 2}, "data": {"options": [{"id": "option-fixed", "label": "Sim", "next": "end"}], "provider_id": "provider-1"}},
        {"id": "end", "type": "message", "position": {"x": 3, "y": 4}, "data": {"text": "fim"}},
    ]
    edges = [{"id": "edge-1", "source": "start", "target": "end", "sourceHandle": "option-fixed", "targetHandle": "input"}]
    return nodes, edges


def test_remap_preserves_options_handles_and_complete_payload():
    nodes, edges = graph()
    cloned_nodes, cloned_edges, mapping = remap_graph(nodes, edges)
    assert mapping.keys() == {"start", "end"}
    assert cloned_nodes[0]["id"] == mapping["start"]
    assert cloned_nodes[0]["data"]["options"][0]["id"] == "option-fixed"
    assert cloned_nodes[0]["data"]["options"][0]["next"] == mapping["end"]
    assert cloned_edges[0]["sourceHandle"] == "option-fixed"
    assert cloned_edges[0]["targetHandle"] == "input"
    assert cloned_edges[0]["source"] == mapping["start"]


def test_sanitizer_only_parameterizes_tenant_bound_values():
    nodes, _ = graph()
    result = sanitize_snapshot({"tenant_id": "tenant-1", "nodes": nodes, "callback": "http://10.0.0.2/private"})
    assert result["tenant_id"] == "{{tenant.id}}"
    assert result["nodes"][0]["data"]["provider_id"] == "{{provider.whatsapp}}"
    assert result["nodes"][0]["data"]["options"][0]["id"] == "option-fixed"
    assert result["callback"] == "{{integration.private_url}}"


def test_structural_comparator_ignores_only_graph_ids_and_timestamps():
    nodes, edges = graph()
    cloned_nodes, cloned_edges, _ = remap_graph(nodes, edges)
    assert structural_diff(nodes, edges, cloned_nodes, cloned_edges)["equivalent"]
    cloned_nodes[0]["data"]["options"][0]["id"] = "different-option"
    assert not structural_diff(nodes, edges, cloned_nodes, cloned_edges)["equivalent"]
    cloned_nodes[0]["data"]["options"][0]["id"] = "option-fixed"
    cloned_edges[0]["sourceHandle"] = "wrong"
    report = structural_diff(nodes, edges, cloned_nodes, cloned_edges)
    assert not report["equivalent"]
    assert report["differences"][0]["path"] == "edges.sourceHandle"


def duplicate_cancel_graph():
    message = "Sem problema. Interrompi o agendamento por enquanto. Quando quiser continuar, é só me chamar."
    nodes = [
        {"id": "start", "type": "choice", "position": {"x": 0, "y": 0}, "data": {"content": "Escolha", "isStart": True}},
        {"id": "origin-a", "type": "message", "position": {"x": -100, "y": 100}, "data": {"content": "A"}},
        {"id": "origin-b", "type": "message", "position": {"x": 100, "y": 100}, "data": {"content": "B"}},
        {"id": "cancel-a", "type": "message", "position": {"x": -2040, "y": -1580}, "data": {"content": message}},
        {"id": "cancel-b", "type": "message", "position": {"x": -3740, "y": -1080}, "data": {"content": message}},
    ]
    edges = [
        {"id": "e0", "source": "start", "target": "origin-a", "sourceHandle": "a", "targetHandle": "input"},
        {"id": "e1", "source": "start", "target": "origin-b", "sourceHandle": "b", "targetHandle": "input"},
        {"id": "e2", "source": "origin-a", "target": "cancel-a", "sourceHandle": "cancel", "targetHandle": "input", "condition": "cancelled"},
        {"id": "e3", "source": "origin-b", "target": "cancel-b", "sourceHandle": "cancel", "targetHandle": "input", "condition": "cancelled"},
    ]
    return nodes, edges


def test_structural_comparator_matches_duplicate_nodes_after_id_and_order_permutation():
    nodes, edges = duplicate_cancel_graph()
    cloned_nodes, cloned_edges, mapping = remap_graph(nodes, edges)
    # Reproduce publication sorting the two duplicate messages into the opposite
    # array slots while their incident edges continue to identify them correctly.
    cloned_nodes[3], cloned_nodes[4] = cloned_nodes[4], cloned_nodes[3]
    cloned_edges = list(reversed(cloned_edges))

    report = structural_diff(nodes, edges, cloned_nodes, cloned_edges, "start", mapping["start"])
    assert report["equivalent"]
    assert report["counts"] == {"nodes": 5, "edges": 4}


def test_structural_comparator_rejects_real_duplicate_graph_divergences():
    nodes, edges = duplicate_cancel_graph()

    def changed(mutator):
        actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
        mutator(actual_nodes, actual_edges, mapping)
        return structural_diff(nodes, edges, actual_nodes, actual_edges, "start", mapping.get("start"))

    # Swap visual identities but leave their incident topology behind.
    assert not changed(lambda ns, _es, _m: (ns[3].__setitem__("position", {"x": -3740, "y": -1080}), ns[4].__setitem__("position", {"x": -2040, "y": -1580})))["equivalent"]
    assert not changed(lambda ns, _es, _m: ns[3]["data"].__setitem__("content", "Outro conteúdo"))["equivalent"]
    assert not changed(lambda ns, _es, _m: ns[3].__setitem__("position", {"x": 999, "y": 999}))["equivalent"]
    assert not changed(lambda _ns, es, _m: es[2].__setitem__("sourceHandle", "success"))["equivalent"]
    assert not changed(lambda _ns, es, _m: es[2].__setitem__("targetHandle", "other"))["equivalent"]
    assert not changed(lambda _ns, es, _m: es[2].__setitem__("condition", "confirmed"))["equivalent"]
    assert not changed(lambda _ns, es, _m: es.pop())["equivalent"]
    assert not changed(lambda _ns, es, _m: es.append(dict(es[0], id="extra")))["equivalent"]
    assert not changed(lambda ns, _es, _m: ns.pop())["equivalent"]
    assert not changed(lambda ns, _es, _m: ns.append(dict(ns[-1], id="extra")))["equivalent"]


def representative_49_node_graph():
    """Production-sized graph; synthetic because the 1.0.4 snapshot is not in git."""
    nodes = []
    for index in range(49):
        node_type = "mcp_tool" if index == 10 else "message"
        data = {"content": f"step-{index}", "template_node_key": f"representative.{index}"}
        if index == 0:
            data["isStart"] = True
        if index == 48:
            data["isEnd"] = True
        if node_type == "mcp_tool":
            data.update({"tool_name": "calendar.get_availability", "arguments": {"service": "consultation"},
                         "result_variable": "availability", "connection_id": "{{integration.connection}}"})
        nodes.append({"id": f"node-{index}", "type": node_type, "position": {"x": index * 10, "y": index * 5}, "data": data})
    edges = []
    for index in range(48):
        edge = {"id": f"edge-{index}", "source": f"node-{index}", "target": f"node-{index + 1}", "targetHandle": "default"}
        if index == 10:
            edge["sourceHandle"] = "success"
        edges.append(edge)
    edges.extend([
        {"id": "edge-extra-1", "source": "node-0", "target": "node-2", "sourceHandle": "default", "targetHandle": "default"},
        {"id": "edge-extra-2", "source": "node-1", "target": "node-3", "sourceHandle": "default", "targetHandle": "default"},
    ])
    return nodes, edges


def test_representative_49_50_remap_publish_pipeline_accepts_only_runtime_false_defaults():
    nodes, edges = representative_49_node_graph()
    remapped_nodes, remapped_edges, mapping = remap_graph(nodes, edges)
    published = FlowV2Publisher().publish(nodes=remapped_nodes, edges=remapped_edges).snapshot

    report = structural_diff(nodes, edges, published["nodes"], published["edges"], "node-0", published["start_node_id"])

    assert report["equivalent"]
    assert report["counts"] == {"nodes": 49, "edges": 50}
    mcp = next(node for node in published["nodes"] if node["type"] == "mcp_tool")
    assert mcp["data"]["allow_external_write"] is False
    assert mcp["data"]["destructive_confirmed"] is False
    assert mapping["node-0"] == published["start_node_id"]


def test_representative_install_pipeline_canonicalizes_only_proven_mcp_alias():
    nodes, edges = representative_49_node_graph()
    timeout_edge = next(edge for edge in edges if edge["source"] == "node-10")
    timeout_edge.update({
        "sourceHandle": "tempo_esgotado",
        "data": {"condition": "tempo_esgotado", "sourceHandle": "tempo_esgotado"},
    })
    remapped_nodes, remapped_edges, mapping = remap_graph(nodes, edges)
    published = FlowV2Publisher().publish(nodes=remapped_nodes, edges=remapped_edges).snapshot

    # Capture the value at every real stage: Marketplace -> remap -> publisher.
    assert timeout_edge["data"]["condition"] == "tempo_esgotado"
    assert next(edge for edge in remapped_edges if edge["source"] == mapping["node-10"])["data"]["condition"] == "tempo_esgotado"
    installed = next(edge for edge in published["edges"] if edge["source"] == mapping["node-10"])
    assert installed["sourceHandle"] == "timeout"
    assert installed["data"]["condition"] == "timeout"

    # Compare against the same closed canonical representation used by Runtime
    # V2; structural comparison itself remains strict.
    expected = FlowV2Publisher().publish(nodes=nodes, edges=edges).snapshot
    report = structural_diff(
        expected["nodes"], expected["edges"], published["nodes"], published["edges"],
        expected["start_node_id"], published["start_node_id"],
    )
    assert report == {"equivalent": True, "differences": [], "counts": {"nodes": 49, "edges": 50}}


def test_timeout_and_error_conditions_remain_functionally_different():
    nodes, edges = representative_49_node_graph()
    edge = next(edge for edge in edges if edge["source"] == "node-10")
    edge.update({"sourceHandle": "timeout", "data": {"condition": "timeout"}})
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    next(edge for edge in actual_edges if edge["source"] == mapping["node-10"])["data"]["condition"] = "error"

    report = structural_diff(nodes, edges, actual_nodes, actual_edges, "node-0", mapping["node-0"])

    assert not report["equivalent"]
    assert report["differences"][0]["kind"] == "edge_relation_mismatch"
    assert report["differences"][0]["path"] == "edges.data.condition"


@pytest.mark.parametrize(("expected", "actual"), [
    ("timeout", "error"),
    ("error", "timeout"),
    ("success", "error"),
    ("success", "timeout"),
])
def test_edge_condition_diagnostic_preserves_strict_safe_branch_values(expected, actual):
    nodes, edges = representative_49_node_graph()
    nodes[10]["data"]["credential"] = "credential-must-never-leak"
    nodes[11]["data"]["content"] = "patient-name-must-never-leak"
    edge = next(item for item in edges if item["source"] == "node-10")
    edge["data"] = {"condition": expected}
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    changed = next(item for item in actual_edges if item["source"] == mapping["node-10"])
    changed["data"]["condition"] = actual

    first = structural_diff(nodes, edges, actual_nodes, actual_edges, "node-0", mapping["node-0"])
    second = structural_diff(nodes, edges, actual_nodes, actual_edges, "node-0", mapping["node-0"])
    issue = first["differences"][0]

    assert not first["equivalent"]
    assert issue["expected"] == {"safe_value": expected}
    assert issue["actual"] == {"safe_value": actual}
    assert issue["source_template_node_key"] == "representative.10"
    assert issue["target_template_node_key"] == "representative.11"
    assert issue["edge_fingerprint"] == second["differences"][0]["edge_fingerprint"]
    assert "patient-name-must-never-leak" not in str(first)
    assert "credential-must-never-leak" not in str(first)


def test_arbitrary_edge_condition_is_described_but_never_exposed():
    nodes, edges = representative_49_node_graph()
    edge = next(item for item in edges if item["source"] == "node-10")
    edge.setdefault("data", {})["condition"] = "timeout"
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    secret = "patient-ref-token-credential-123"
    next(item for item in actual_edges if item["source"] == mapping["node-10"])["data"]["condition"] = secret

    report = structural_diff(nodes, edges, actual_nodes, actual_edges, "node-0", mapping["node-0"])
    descriptor = report["differences"][0]["actual"]

    assert descriptor == {
        "value_type": "str", "value_length": len(secret),
        "short_hash": __import__("hashlib").sha256(secret.encode()).hexdigest()[:12],
    }
    assert secret not in str(report)


def test_marketplace_legacy_boundary_tracks_timeout_edge_through_real_pipeline():
    """Regression for the asymmetric expected-vs-published install comparison."""
    nodes, edges = representative_49_node_graph()
    mcp = next(node for node in nodes if node["id"] == "node-10")
    mcp["data"].update({
        "tool_name": "google_calendar_check_availability",
        "template_node_key": "assistant.calendar.availability",
    })
    timeout = next(edge for edge in edges if edge["source"] == "node-10")
    timeout.update({
        "sourceHandle": "tempo_esgotado",
        "data": {"sourceHandle": "tempo_esgotado", "condition": "tempo_esgotado"},
    })

    # A: immutable Marketplace payload; B: remap; C/D: the publisher boundary.
    checkpoint_a = (timeout["sourceHandle"], timeout["data"]["sourceHandle"], timeout["data"]["condition"])
    remapped_nodes, remapped_edges, mapping = remap_graph(nodes, edges)
    before = next(edge for edge in remapped_edges if edge["source"] == mapping["node-10"])
    checkpoint_b = (before["sourceHandle"], before["data"]["sourceHandle"], before["data"]["condition"])
    migrated = migrate_edge_handles(remapped_nodes, remapped_edges)
    after = next(edge for edge in migrated if edge["source"] == mapping["node-10"])
    checkpoint_cd = (before["sourceHandle"], before["data"]["sourceHandle"], before["data"]["condition"],
                     after["sourceHandle"], after["data"]["sourceHandle"], after["data"]["condition"])
    published = FlowV2Publisher().publish(nodes=remapped_nodes, edges=remapped_edges).snapshot
    final = next(edge for edge in published["edges"] if edge["source"] == mapping["node-10"])
    checkpoint_efg = (final["sourceHandle"], final["data"]["sourceHandle"], final["data"]["condition"])

    assert checkpoint_a == checkpoint_b == ("tempo_esgotado", "tempo_esgotado", "tempo_esgotado")
    assert checkpoint_cd == ("tempo_esgotado", "tempo_esgotado", "tempo_esgotado", "timeout", "timeout", "timeout")
    assert checkpoint_efg == ("timeout", "timeout", "timeout")
    expected_edges = publication_boundary_edges(nodes, edges)
    assert structural_diff(nodes, expected_edges, published["nodes"], published["edges"],
                           "node-0", published["start_node_id"])["equivalent"]


@pytest.mark.parametrize(("expected", "actual"), [
    ("timeout", "error"), ("error", "timeout"),
    ("success", "error"), ("success", "timeout"),
])
def test_publication_boundary_never_equates_distinct_mcp_branches(expected, actual):
    nodes, edges = representative_49_node_graph()
    edge = next(item for item in edges if item["source"] == "node-10")
    edge.update({"sourceHandle": expected, "data": {"sourceHandle": expected, "condition": expected}})
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    changed = next(item for item in actual_edges if item["source"] == mapping["node-10"])
    changed["sourceHandle"] = actual
    changed["data"]["sourceHandle"] = actual
    changed["data"]["condition"] = actual

    report = structural_diff(nodes, publication_boundary_edges(nodes, edges), actual_nodes, actual_edges,
                             "node-0", mapping["node-0"])
    assert not report["equivalent"]


@pytest.mark.parametrize("mutation", [
    "content", "position", "sourceHandle", "targetHandle", "condition", "remove_edge", "add_edge",
    "remove_node", "add_node", "wrong_target", "tool_name", "arguments", "result_variable", "choice_option",
    "template_node_key", "source", "data.condition", "data.sourceHandle",
])
def test_structural_comparator_rejects_required_functional_divergences(mutation):
    nodes, edges = graph()
    nodes[0]["data"].update({"template_node_key": "assistant.services", "result_variable": "selected",
                             "tool_name": "calendar.get_availability", "arguments": {"day": "today"}})
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    if mutation == "content": actual_nodes[1]["data"]["text"] = "alterado"
    elif mutation == "position": actual_nodes[1]["position"]["x"] = 999
    elif mutation == "sourceHandle": actual_edges[0]["sourceHandle"] = "other"
    elif mutation == "targetHandle": actual_edges[0]["targetHandle"] = "other"
    elif mutation == "condition": actual_edges[0]["condition"] = "different"
    elif mutation == "remove_edge": actual_edges.pop()
    elif mutation == "add_edge": actual_edges.append({**actual_edges[0], "id": "extra"})
    elif mutation == "remove_node": actual_nodes.pop()
    elif mutation == "add_node": actual_nodes.append({"id": "extra", "type": "message", "data": {"text": "extra"}})
    elif mutation == "wrong_target": actual_edges[0]["target"] = mapping["start"]
    elif mutation == "tool_name": actual_nodes[0]["data"]["tool_name"] = "calendar.create_appointment"
    elif mutation == "arguments": actual_nodes[0]["data"]["arguments"]["day"] = "tomorrow"
    elif mutation == "result_variable": actual_nodes[0]["data"]["result_variable"] = "other"
    elif mutation == "choice_option": actual_nodes[0]["data"]["options"][0]["label"] = "Não"
    elif mutation == "template_node_key": actual_nodes[0]["data"]["template_node_key"] = "assistant.other"
    elif mutation == "source": actual_edges[0]["source"] = mapping["end"]
    elif mutation == "data.condition": actual_edges[0].setdefault("data", {})["condition"] = "error"
    elif mutation == "data.sourceHandle": actual_edges[0].setdefault("data", {})["sourceHandle"] = "error"
    assert not structural_diff(nodes, edges, actual_nodes, actual_edges, "start", mapping.get("start"))["equivalent"]


def test_structural_diagnostic_is_typed_deterministic_and_does_not_expose_content():
    nodes, edges = graph()
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    secret_message = "patient-name token-super-secret"
    actual_nodes[1]["data"]["text"] = secret_message
    report = structural_diff(nodes, edges, actual_nodes, actual_edges, "start", mapping["start"])
    difference = report["differences"][0]
    assert difference["kind"] == "node_attribute_mismatch"
    assert difference["field"] == "data.text"
    assert difference["actual"]["value_length"] == len(secret_message)
    assert secret_message not in str(report)


def test_explicit_true_mcp_permission_remains_a_functional_divergence():
    nodes, edges = representative_49_node_graph()
    actual_nodes, actual_edges, mapping = remap_graph(nodes, edges)
    next(node for node in actual_nodes if node["type"] == "mcp_tool")["data"]["allow_external_write"] = True
    report = structural_diff(nodes, edges, actual_nodes, actual_edges, "node-0", mapping["node-0"])
    assert not report["equivalent"]
    assert report["differences"][0]["kind"] == "node_attribute_mismatch"
