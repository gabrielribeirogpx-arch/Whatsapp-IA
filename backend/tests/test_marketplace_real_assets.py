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
        {"x": 1450, "y": 0}, {"x": 1450, "y": 300}, {"x": 1450, "y": 600},
    ]
    assert nodes["menu_end"]["position"] == {"x": 1750, "y": 300}
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


def test_hybrid_service_fallback_is_an_explicit_runtime_v2_composition():
    asset = ASSETS["atendimento_com_fallback_para_ia"]
    nodes = {node["key"]: node for node in asset["graph"]["nodes"]}
    edges = asset["graph"]["edges"]

    assert len(nodes) == 14
    assert "hybrid_resolved_condition" not in nodes
    assert "ai_system" not in {node["type"] for node in nodes.values()}
    assert nodes["hybrid_ai"]["type"] == "ai_classification"
    assert nodes["hybrid_handoff"]["config"]["action"] == "human_handoff"
    assert nodes["hybrid_wait"]["config"]["content"] == "Aguarde um atendente."
    assert nodes["hybrid_welcome"]["config"]["content"] == "Olá {{contact.name}}!"

    menu_edges = [edge for edge in edges if edge["source"] == "hybrid_menu"]
    assert [(edge["source_handle"], edge["target"]) for edge in menu_edges] == [
        ("atendimento", "hybrid_atendimento"),
        ("comercial", "hybrid_comercial"),
        ("financeiro", "hybrid_financeiro"),
    ]
    assert all(any(edge["source"] == f"hybrid_{route}" and edge["target"] == "hybrid_resolved_question" for edge in edges) for route in ("atendimento", "comercial", "financeiro"))
    resolved_edges = [edge for edge in edges if edge["source"] == "hybrid_resolved_question"]
    assert [(edge["source_handle"], edge["target"]) for edge in resolved_edges] == [
        ("sim", "hybrid_closed"),
        ("nao", "hybrid_ai"),
    ]
    assert any(edge["source"] == "hybrid_ai_condition" and edge["source_handle"] == "true" and edge["target"] == "hybrid_handoff" for edge in edges)


def test_hybrid_service_fallback_classifier_has_safe_production_configuration():
    """Keep the Marketplace learning example explicit across its storage boundary."""
    from app.services.marketplace_installation_service import MarketplaceInstallationService

    asset = ASSETS["atendimento_com_fallback_para_ia"]
    nodes = {node["key"]: node for node in asset["graph"]["nodes"]}
    classifier = nodes["hybrid_ai"]["config"]
    condition = nodes["hybrid_ai_condition"]["config"]

    assert classifier["instruction"].strip()
    assert classifier["input_template"] == "{{last_message}}"
    assert classifier["categories"] == ["financeiro", "vendas", "suporte", "outro"]
    assert classifier["confidence_threshold"] == 0.75
    assert classifier["output_variable"] == "intent_category"
    assert classifier["allow_other"] is True
    assert classifier["fallback"] == classifier["error_fallback"] == "outro"
    assert condition["conditions"] == [
        {"field": "intent_category", "operator": "equals", "value": "outro"}
    ]

    outgoing = {
        edge["source_handle"]: edge["target"]
        for edge in asset["graph"]["edges"]
        if edge["source"] == "hybrid_ai_condition"
    }
    assert outgoing == {"false": "hybrid_specific", "true": "hybrid_handoff"}
    assert "ai_identified" not in json.dumps(asset, ensure_ascii=False)

    materialized_nodes, materialized_edges = MarketplaceInstallationService._materialize(asset)
    persisted = json.loads(json.dumps({"nodes": materialized_nodes, "edges": materialized_edges}))
    persisted_classifier = next(node for node in persisted["nodes"] if node["type"] == "ai_classification")
    persisted_condition = next(node for node in persisted["nodes"] if node["type"] == "condition")
    assert persisted_classifier["data"]["output_variable"] == "intent_category"
    assert persisted_classifier["data"]["categories"] == classifier["categories"]
    assert persisted_classifier["data"]["confidence_threshold"] == 0.75
    assert persisted_condition["data"]["conditions"] == condition["conditions"]
    assert not any(
        key in persisted_condition["data"]
        for key in ("condition", "keywords", "positive", "question", "text")
    )
    assert len(persisted["nodes"]) == len(asset["graph"]["nodes"]) == 14
    assert len(persisted["edges"]) == len(asset["graph"]["edges"]) == 15

    from app.flow_v2.publisher import FlowV2Publisher

    publication = FlowV2Publisher().publish(
        nodes=persisted["nodes"], edges=persisted["edges"]
    )
    snapshot_condition = next(
        node for node in publication.snapshot["nodes"] if node["type"] == "condition"
    )
    assert snapshot_condition["data"]["conditions"] == condition["conditions"]
    assert len(publication.snapshot["edges"]) == len(persisted["edges"])


def test_hybrid_service_fallback_asset_has_complete_visual_graph_integrity():
    """Automatically guard every authored and materialized connection in this asset."""
    from app.services.marketplace_installation_service import MarketplaceInstallationService

    graph = ASSETS["atendimento_com_fallback_para_ia"]["graph"]
    nodes = {node["key"]: node for node in graph["nodes"]}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph["edges"]:
        assert edge["source"] in nodes
        assert edge["target"] in nodes
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]].append(edge)

    terminal = {key for key, node in nodes.items() if node["config"].get("isEnd")}
    assert terminal == {"hybrid_closed", "hybrid_specific", "hybrid_wait"}
    assert all(incoming[key] for key in nodes if key != "start")
    assert all(outgoing[key] for key in nodes if key not in terminal)

    reached, queue = set(), deque(["start"])
    while queue:
        key = queue.popleft()
        if key in reached:
            continue
        reached.add(key)
        queue.extend(edge["target"] for edge in outgoing[key])
    assert reached == set(nodes)

    for key, node in nodes.items():
        if node["type"] == "condition":
            assert len(outgoing[key]) == 2
            assert {edge["source_handle"] for edge in outgoing[key]} == {"true", "false"}

    assert [(edge["source_handle"], edge["target"]) for edge in outgoing["hybrid_resolved_question"]] == [
        ("sim", "hybrid_closed"),
        ("nao", "hybrid_ai"),
    ]
    assert [edge["target"] for edge in outgoing["hybrid_ai"]] == ["hybrid_ai_condition"]
    assert [(edge["source_handle"], edge["target"]) for edge in outgoing["hybrid_ai_condition"]] == [
        ("false", "hybrid_specific"),
        ("true", "hybrid_handoff"),
    ]
    assert [edge["target"] for edge in outgoing["hybrid_handoff"]] == ["hybrid_wait"]

    materialized_nodes, materialized_edges = MarketplaceInstallationService._materialize(
        ASSETS["atendimento_com_fallback_para_ia"]
    )
    materialized_ids = {node["id"] for node in materialized_nodes}
    assert len(materialized_edges) == len(graph["edges"])
    assert all(edge["source"] in materialized_ids and edge["target"] in materialized_ids for edge in materialized_edges)
    assert all(edge.get("id") and edge.get("type") for edge in materialized_edges)

    # JSON is the same storage boundary used by Flow.edges_json. Handles must
    # remain byte-for-byte stable through materialization and serialization.
    persisted_edges = json.loads(json.dumps(materialized_edges))
    key_by_id = {
        node["id"]: original["key"]
        for node, original in zip(materialized_nodes, graph["nodes"])
    }
    persisted_by_pair = {
        (key_by_id[edge["source"]], key_by_id[edge["target"]]): edge
        for edge in persisted_edges
    }
    expected_handles = {
        ("hybrid_resolved_question", "hybrid_closed"): "sim",
        ("hybrid_resolved_question", "hybrid_ai"): "nao",
        ("hybrid_ai", "hybrid_ai_condition"): "default",
        ("hybrid_ai_condition", "hybrid_specific"): "false",
        ("hybrid_ai_condition", "hybrid_handoff"): "true",
        ("hybrid_handoff", "hybrid_wait"): "default",
    }
    assert {
        pair: persisted_by_pair[pair]["sourceHandle"]
        for pair in expected_handles
    } == expected_handles

    # Runtime V2 consumes the very same materialized handles when it builds
    # transitions. Exercise both condition branches and each default output.
    from app.flow_v2.snapshot import build_transitions_from_edges
    from app.flow_v2.transition_resolver import TransitionResolver

    transitions = build_transitions_from_edges(persisted_edges)
    ids_by_key = {original["key"]: node["id"] for node, original in zip(materialized_nodes, graph["nodes"])}
    for (source_key, target_key), handle in expected_handles.items():
        matches = TransitionResolver._matches(
            transitions=transitions,
            source_node_id=ids_by_key[source_key],
            source_handle=None if handle == "default" else handle,
        )
        assert [match["target_node_id"] for match in matches] == [ids_by_key[target_key]]


def test_hybrid_validator_rejects_a_handle_that_react_flow_does_not_render():
    from copy import deepcopy

    asset = deepcopy(ASSETS["atendimento_com_fallback_para_ia"])
    edge = next(edge for edge in asset["graph"]["edges"] if edge["source"] == "hybrid_ai_condition")
    edge["source_handle"] = "sim"

    with pytest.raises(MarketplaceGraphValidationError, match="condition_handle_requires_one_edge|invalid_condition_edge_handle"):
        MarketplaceGraphValidator().validate(asset)


def test_hybrid_service_fallback_uses_authored_left_to_right_columns():
    asset = ASSETS["atendimento_com_fallback_para_ia"]
    nodes = {node["key"]: node for node in asset["graph"]["nodes"]}

    assert asset["metadata"]["layout_direction"] == "LR"
    assert asset["metadata"]["column_count"] == 10
    assert [nodes[key]["position"] for key in ("start", "hybrid_welcome", "hybrid_register", "hybrid_menu")] == [
        {"x": 0, "y": 360},
        {"x": 320, "y": 360},
        {"x": 640, "y": 360},
        {"x": 960, "y": 360},
    ]
    assert {nodes[f"hybrid_{route}"]["position"]["x"] for route in ("atendimento", "comercial", "financeiro")} == {1500}
    assert [nodes[f"hybrid_{route}"]["position"]["y"] for route in ("atendimento", "comercial", "financeiro")] == [40, 360, 680]
    assert nodes["hybrid_resolved_question"]["position"] == {"x": 1820, "y": 360}
    assert nodes["hybrid_closed"]["position"] == {"x": 2140, "y": 40}
    assert nodes["hybrid_ai"]["position"] == {"x": 2140, "y": 520}
    assert all(nodes[edge["target"]]["position"]["x"] > nodes[edge["source"]]["position"]["x"] for edge in asset["graph"]["edges"])
    condition = nodes["hybrid_ai_condition"]
    assert condition["position"] == {"x": 2460, "y": 520}
    assert condition["config"]["branches"] == [
        {"id": "false", "label": "Não", "handleId": "false"},
        {"id": "true", "label": "Sim", "handleId": "true"},
    ]
    assert nodes["hybrid_specific"]["position"] == {"x": 2780, "y": 400}
    assert nodes["hybrid_handoff"]["position"] == {"x": 2780, "y": 640}
    assert nodes["hybrid_wait"]["position"] == {"x": 3100, "y": 640}
    assert nodes["hybrid_specific"]["position"]["y"] < condition["position"]["y"]
    assert nodes["hybrid_handoff"]["position"]["y"] > condition["position"]["y"]
    assert nodes["hybrid_wait"]["position"]["y"] == nodes["hybrid_handoff"]["position"]["y"]
    required_learning_fields = {"purpose", "when_to_use", "best_practices", "common_mistakes", "alternatives"}
    assert all(required_learning_fields <= set(asset["educational_metadata"][key]) for key in nodes)


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
