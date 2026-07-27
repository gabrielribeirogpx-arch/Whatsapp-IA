from collections import defaultdict, deque
import json

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
        minimum_nodes = 8 if key == "menu_inicial" else 15
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


def test_initial_menu_is_a_complete_acyclic_three_branch_reference_flow():
    asset = ASSETS["menu_inicial"]
    graph = asset["graph"]
    nodes = {node["key"]: node for node in graph["nodes"]}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["source"]].append(edge["target"])
        incoming[edge["target"]].append(edge["source"])

    assert len(nodes) == 8
    assert len(graph["edges"]) == 9
    assert asset["metadata"]["branch_count"] == 3
    assert [node["key"] for node in graph["nodes"] if node["type"] == "choice"] == ["menu_main"]
    assert not {"menu_more_1", "menu_more_2", "menu_agendamento", "menu_faq", "menu_humano"} & nodes.keys()

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

    buttons = nodes["menu_main"]["config"]["buttons"]
    assert [button["label"] for button in buttons] == ["Atendimento", "Comercial", "Financeiro"]
    assert [button["handleId"] for button in buttons] == ["atendimento", "comercial", "financeiro"]
    route_edges = [edge for edge in graph["edges"] if edge["source"] == "menu_main"]
    assert [edge["source_handle"] for edge in route_edges] == ["atendimento", "comercial", "financeiro"]
    assert [edge["target"] for edge in route_edges] == ["menu_atendimento", "menu_comercial", "menu_financeiro"]


def test_initial_menu_layout_is_uniform_left_to_right_without_crossings():
    asset = ASSETS["menu_inicial"]
    nodes = {node["key"]: node for node in asset["graph"]["nodes"]}
    branch_keys = ["atendimento", "comercial", "financeiro"]

    main = ("start", "menu_welcome", "menu_identification", "menu_main")
    assert [nodes[key]["position"] for key in main] == [
        {"x": 0, "y": 300}, {"x": 300, "y": 300},
        {"x": 600, "y": 300}, {"x": 900, "y": 300},
    ]
    assert [nodes[f"menu_{key}"]["position"] for key in branch_keys] == [
        {"x": 1200, "y": 0}, {"x": 1200, "y": 300}, {"x": 1200, "y": 600},
    ]
    assert nodes["menu_end"]["position"] == {"x": 1500, "y": 300}
    assert asset["metadata"]["layout_direction"] == "LR"
    assert all(nodes[edge["target"]]["position"]["x"] > nodes[edge["source"]]["position"]["x"] for edge in asset["graph"]["edges"])
    assert all(
        [edge["target"] for edge in asset["graph"]["edges"] if edge["source"] == f"menu_{key}"] == ["menu_end"]
        for key in branch_keys
    )


def test_initial_menu_choice_contract_survives_installation_round_trip():
    from app.services.marketplace_installation_service import MarketplaceInstallationService

    persisted_nodes, persisted_edges = MarketplaceInstallationService._materialize(ASSETS["menu_inicial"])
    loaded = json.loads(json.dumps({"nodes": persisted_nodes, "edges": persisted_edges}))
    nodes = {node["id"]: node for node in loaded["nodes"]}
    choice_nodes = [node for node in nodes.values() if node["type"] == "choice"]

    assert len(choice_nodes) == 1
    choice = choice_nodes[0]
    assert choice["data"]["display_mode"] == "buttons"
    assert "options" not in choice["data"]
    option_handles = [button["handleId"] for button in choice["data"]["buttons"]]
    assert option_handles == ["atendimento", "comercial", "financeiro"]
    assert [button["id"] for button in choice["data"]["buttons"]] == option_handles
    assert [button["value"] for button in choice["data"]["buttons"]] == option_handles

    choice_edges = [edge for edge in loaded["edges"] if edge["source"] == choice["id"]]
    assert [edge["sourceHandle"] for edge in choice_edges] == option_handles
    assert len({edge["target"] for edge in choice_edges}) == 3

    outgoing = defaultdict(list)
    for edge in loaded["edges"]:
        assert edge["source"] in nodes
        assert edge["target"] in nodes
        outgoing[edge["source"]].append(edge["target"])
    start = next(node["id"] for node in nodes.values() if node["type"] == "start")
    reached, queue = set(), deque([start])
    while queue:
        node_id = queue.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        queue.extend(outgoing[node_id])
    assert reached == set(nodes)


def test_materialization_preserves_all_react_flow_edge_handle_fields():
    from copy import deepcopy
    from app.services.marketplace_installation_service import MarketplaceInstallationService

    asset = deepcopy(ASSETS["menu_inicial"])
    first_edge = asset["graph"]["edges"][0]
    first_edge.update({"sourceHandle": "default", "targetHandle": "default", "type": "smoothstep", "animated": True})

    _, edges = MarketplaceInstallationService._materialize(asset)

    assert edges[0]["sourceHandle"] == "default"
    assert edges[0]["targetHandle"] == "default"
    assert edges[0]["type"] == "smoothstep"
    assert edges[0]["animated"] is True


def test_validator_blocks_menu_choice_with_a_missing_or_unknown_connection():
    from copy import deepcopy

    for mutation in ("missing", "unknown"):
        asset = deepcopy(ASSETS["menu_inicial"])
        if mutation == "missing":
            asset["graph"]["edges"] = [edge for edge in asset["graph"]["edges"] if edge.get("source_handle") != "financeiro"]
        else:
            edge = next(edge for edge in asset["graph"]["edges"] if edge.get("source_handle") == "financeiro")
            edge["source_handle"] = "handle_inexistente"

        with pytest.raises(MarketplaceGraphValidationError, match="choice_"):
            MarketplaceGraphValidator().validate(asset)
