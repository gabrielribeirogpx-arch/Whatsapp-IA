from collections import defaultdict, deque

import pytest
from app.marketplace_assets import ASSETS, ITEMS, MarketplaceGraphValidator
from app.marketplace_assets.validator import MarketplaceGraphValidationError


def test_all_catalogued_assets_are_valid_runtime_v2_graphs():
    validator = MarketplaceGraphValidator()
    for asset in ASSETS.values():
        validator.validate(asset)


def test_no_ai_templates_have_distinct_real_graphs_without_ai_system():
    keys = [key for key, item in ITEMS.items() if item["template_type"] == "flow_template"]
    signatures = set()
    for key in keys:
        graph = ASSETS[key]["graph"]
        minimum_nodes = 11 if key == "menu_inicial" else 15
        assert len(graph["nodes"]) >= minimum_nodes
        assert not any(node["type"].startswith("ai_") for node in graph["nodes"])
        signatures.add(tuple((node["key"], node["type"]) for node in graph["nodes"]))
    assert len(signatures) == len(keys)


def test_hybrid_and_ai_system_items_are_visible_compositions():
    for item in ITEMS.values():
        if item["template_type"] not in {"hybrid_flow", "ai_system"}: continue
        nodes = ASSETS[item["flow_assets"][0]]["graph"]["nodes"]
        assert any(node["type"].startswith("ai_") for node in nodes)
        assert any(not node["type"].startswith("ai_") for node in nodes)
        assert all(node["type"] != "ai_system" for node in nodes)


def test_dentistry_and_other_segments_are_structurally_distinct():
    dental = ITEMS["clinica_odontologica"]["flow_assets"]
    assert len(dental) == 12
    assert all("odontol" in ASSETS[key]["name"].lower() or key.startswith("odontologia_") for key in dental)
    segment_signatures = {segment: tuple(node["config"].get("content", "") for node in ASSETS[item["flow_assets"][0]]["graph"]["nodes"]) for segment, item in ITEMS.items() if segment in {"imobiliaria", "restaurante", "advocacia"}}
    assert len(set(segment_signatures.values())) == 3


def test_every_installed_node_teaches_automation_architecture():
    required = {"purpose", "when_to_use", "best_practices", "alternatives", "common_mistakes", "input", "output", "why_here"}
    for asset in ASSETS.values():
        assert set(asset["educational_metadata"]) == {node["key"] for node in asset["graph"]["nodes"]}
        assert all(required <= set(metadata) for metadata in asset["educational_metadata"].values())


def test_business_kits_install_twelve_independent_domain_flows():
    for key in ("clinica_odontologica", "imobiliaria", "restaurante", "advocacia"):
        assets = ITEMS[key]["flow_assets"]
        assert len(assets) == 12
        assert len(set(assets)) == 12
        assert all(len(ASSETS[asset]["graph"]["nodes"]) >= 15 for asset in assets)


def test_validator_rejects_invalid_edge_or_orphan():
    asset = dict(ASSETS["menu_inicial"])
    asset["graph"] = {"nodes": list(asset["graph"]["nodes"]), "edges": [{"source": "start", "target": "missing"}]}
    with pytest.raises(MarketplaceGraphValidationError): MarketplaceGraphValidator().validate(asset)


def test_initial_menu_is_a_complete_acyclic_six_branch_reference_flow():
    asset = ASSETS["menu_inicial"]
    graph = asset["graph"]
    nodes = {node["key"]: node for node in graph["nodes"]}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["source"]].append(edge["target"])
        incoming[edge["target"]].append(edge["source"])

    assert len(nodes) == 11
    assert len(graph["edges"]) == 15
    assert asset["metadata"]["branch_count"] == 6
    assert asset["metadata"]["layout"] == "manual"
    assert not [node for node in nodes.values() if node["type"] == "condition"]

    reached = set()
    queue = deque(["start"])
    while queue:
        key = queue.popleft()
        if key in reached:
            continue
        reached.add(key)
        queue.extend(outgoing[key])
    assert reached == set(nodes)
    assert all(incoming[key] for key in nodes if key != "start")
    assert outgoing["menu_end"] == []
    assert all(outgoing[key] for key in nodes if key != "menu_end")

    # Kahn's algorithm proves there is no cycle (and therefore no infinite loop).
    remaining_incoming = {key: len(incoming[key]) for key in nodes}
    roots = deque(key for key, count in remaining_incoming.items() if count == 0)
    ordered = []
    while roots:
        key = roots.popleft()
        ordered.append(key)
        for target in outgoing[key]:
            remaining_incoming[target] -= 1
            if remaining_incoming[target] == 0:
                roots.append(target)
    assert len(ordered) == len(nodes)

    router_edges = [edge for edge in graph["edges"] if edge["source"] == "menu_main"]
    option_ids = {option["id"] for option in nodes["menu_main"]["config"]["options"]}
    assert {edge["source_handle"] for edge in router_edges} == option_ids
    assert len(router_edges) == len(option_ids) == 6
    assert all(outgoing[edge["target"]] for edge in router_edges)


def test_initial_menu_layout_has_aligned_rows_and_complete_learning_metadata():
    asset = ASSETS["menu_inicial"]
    nodes = {node["key"]: node for node in asset["graph"]["nodes"]}
    branch_keys = ["atendimento", "comercial", "financeiro", "agendamento", "faq", "humano"]

    assert [nodes[key]["position"]["x"] for key in ("start", "menu_welcome", "menu_identification", "menu_main", "menu_end")] == [900] * 5
    assert [nodes[f"menu_{key}"]["position"]["y"] for key in branch_keys] == [780] * 6
    assert [nodes[f"menu_{key}"]["position"]["x"] for key in branch_keys] == sorted(nodes[f"menu_{key}"]["position"]["x"] for key in branch_keys)
    for key in branch_keys:
        targets = [edge["target"] for edge in asset["graph"]["edges"] if edge["source"] == f"menu_{key}"]
        assert targets == ["menu_end"]

    required_learning_fields = {"purpose", "when_to_use", "best_practices", "common_mistakes", "input", "output"}
    assert set(asset["educational_metadata"]) == set(nodes)
    assert all(required_learning_fields <= metadata.keys() for metadata in asset["educational_metadata"].values())
