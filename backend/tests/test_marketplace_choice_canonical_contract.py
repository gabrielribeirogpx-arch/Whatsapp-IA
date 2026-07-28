from copy import deepcopy

import pytest

from app.flow_builder_contract import create_choice_node
from app.flow_v2.publisher import FlowV2Publisher
from app.flow_v2.snapshot import build_transitions_from_edges
from app.flow_v2.transition_resolver import TransitionResolver
from app.marketplace_assets import ASSETS, MarketplaceGraphValidationError, MarketplaceGraphValidator
from app.services.marketplace_installation_service import MarketplaceInstallationService


def _hybrid_graph():
    asset = ASSETS["atendimento_com_fallback_para_ia"]
    nodes, edges = MarketplaceInstallationService._materialize(asset)
    authored = asset["graph"]["nodes"]
    by_key = {raw["key"]: node for raw, node in zip(authored, nodes)}
    return asset, by_key, edges


@pytest.mark.parametrize("key", ["hybrid_menu", "hybrid_resolved_question"])
def test_marketplace_choice_is_structurally_equal_to_editor_factory(key):
    asset, by_key, _ = _hybrid_graph()
    raw = next(node for node in asset["graph"]["nodes"] if node["key"] == key)
    marketplace = by_key[key]
    expected = create_choice_node(
        node_id=marketplace["id"], position=raw["position"],
        data={**raw["config"], "marketplace_asset_key": asset["key"],
              "educational_metadata": asset["educational_metadata"][key]},
    )
    assert marketplace == expected


def test_all_five_choice_buttons_survive_publish_and_resolve_the_expected_branch():
    _, by_key, edges = _hybrid_graph()
    publication = FlowV2Publisher().publish(nodes=list(by_key.values()), edges=edges)
    transitions = build_transitions_from_edges(publication.snapshot["edges"])
    expected = {
        ("hybrid_menu", "atendimento"): "hybrid_atendimento",
        ("hybrid_menu", "comercial"): "hybrid_comercial",
        ("hybrid_menu", "financeiro"): "hybrid_financeiro",
        ("hybrid_resolved_question", "sim"): "hybrid_closed",
        ("hybrid_resolved_question", "nao"): "hybrid_ai",
    }
    for (source, handle), target in expected.items():
        matches = TransitionResolver._matches(
            transitions=transitions, source_node_id=by_key[source]["id"], source_handle=handle,
        )
        assert [match["target_node_id"] for match in matches] == [by_key[target]["id"]]
        snapshot_node = next(node for node in publication.snapshot["nodes"] if node["id"] == by_key[source]["id"])
        option = next(button for button in snapshot_node["data"]["buttons"] if button["handleId"] == handle)
        assert option["id"] and option["value"] and option["next"] == ""


@pytest.mark.parametrize("mutation", ["missing_option_id", "duplicate_handle", "edge_data_mismatch"])
def test_materialized_validator_blocks_noncanonical_choice_before_persistence(mutation):
    _, by_key, edges = _hybrid_graph()
    nodes = list(by_key.values())
    if mutation == "missing_option_id":
        del by_key["hybrid_menu"]["data"]["buttons"][0]["id"]
    elif mutation == "duplicate_handle":
        by_key["hybrid_menu"]["data"]["buttons"][1]["handleId"] = "atendimento"
    else:
        edge = next(edge for edge in edges if edge["source"] == by_key["hybrid_menu"]["id"])
        edge["data"]["sourceHandle"] = "wrong"
    with pytest.raises(MarketplaceGraphValidationError):
        MarketplaceGraphValidator().validate_materialized(deepcopy(nodes), deepcopy(edges))
