import pytest

from app.services.marketplace_installation_service import CHECKLIST, COPIES, FIELDS, FLOWS, PIPELINE, TAGS, dentistry_manifest


@pytest.mark.parametrize("variant,knowledge,agents", [("Sem IA", 0, 0), ("Híbrida", 1, 1), ("IA Completa", 1, 1)])
def test_dentistry_variants_only_declare_compatible_ai_resources(variant, knowledge, agents):
    manifest = dentistry_manifest(variant)
    assert len(manifest["knowledge_bases"]) == knowledge
    assert len(manifest["ai_agents"]) == agents
    assert manifest["flows"] == FLOWS


def test_dentistry_production_inventory_is_complete():
    assert len(FLOWS) == 12
    assert len(PIPELINE) == 11
    assert len(TAGS) == 10
    assert len(FIELDS) == 9
    assert len(CHECKLIST) == 10
    assert {"Recepção inicial", "Confirmação", "Lembrete", "Transferência humana"} <= COPIES.keys()


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="variant_not_supported"):
        dentistry_manifest("inventada")
