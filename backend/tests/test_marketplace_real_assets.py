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
        assert len(graph["nodes"]) >= 5
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


def test_validator_rejects_invalid_edge_or_orphan():
    asset = dict(ASSETS["menu_inicial"])
    asset["graph"] = {"nodes": list(asset["graph"]["nodes"]), "edges": [{"source": "start", "target": "missing"}]}
    with pytest.raises(MarketplaceGraphValidationError): MarketplaceGraphValidator().validate(asset)
