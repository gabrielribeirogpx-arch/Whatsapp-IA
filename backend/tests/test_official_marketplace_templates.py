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
    assert report["differences"][0]["path"] == "edges[0]"
