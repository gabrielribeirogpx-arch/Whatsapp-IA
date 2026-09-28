from app.services.official_marketplace_template_service import remap_graph, sanitize_snapshot, structural_diff


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
    assert report["differences"][0]["path"] == "graph"


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
