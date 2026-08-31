
from app.flow_v2.flow_v1_to_v2_migrator import FlowV1ToV2Migrator
from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.flow_v2.node_executors import EXECUTOR_REGISTRY
from app.flow_v2.node_registry import (
    EXECUTABLE_NATIVE_NODE_TYPES,
    MIGRATABLE_NODE_TYPES,
    NATIVE_NODE_REGISTRY,
    PUBLISHABLE_NODE_TYPES,
)
from app.flow_v2.publisher import FlowV2Publisher


def _graph():
    nodes = [
        {
            "id": "collect",
            "type": "data_collection",
            "data": {
                "isStart": True,
                "variable_name": "email",
                "data_type": "email",
                "prompt": "Qual é o seu e-mail?",
            },
        },
        {"id": "done", "type": "message", "data": {"content": "Obrigado", "isEnd": True}},
    ]
    edges = [{"id": "success", "source": "collect", "sourceHandle": "success", "target": "done"}]
    return nodes, edges


def test_data_collection_is_native_in_every_node_type_registry() -> None:
    assert "data_collection" in NATIVE_NODE_REGISTRY
    assert "data_collection" in PUBLISHABLE_NODE_TYPES
    assert "data_collection" in MIGRATABLE_NODE_TYPES
    assert "data_collection" in EXECUTABLE_NATIVE_NODE_TYPES
    assert "data_collection" in FlowV2GraphValidator.SUPPORTED_NODE_TYPES
    assert EXECUTOR_REGISTRY["data_collection"].__name__ == "RuntimeV2DataCollectionExecutor"


def test_data_collection_survives_save_conversion_and_publish() -> None:
    nodes, edges = _graph()

    migrated = FlowV1ToV2Migrator().migrate_payload(nodes=nodes, edges=edges)
    migrated_collection = next(node for node in migrated.snapshot["nodes"] if node["id"] == "collect")
    assert migrated_collection["type"] == "data_collection"
    assert not any("MAPPED_TO_MESSAGE" in warning for warning in migrated.warnings)

    validation = FlowV2GraphValidator().validate(nodes=nodes, edges=edges)
    assert validation.status == GraphValidationStatus.VALID
    published = FlowV2Publisher().publish(nodes=nodes, edges=edges)
    assert published.snapshot["start_node_id"] == "collect"
    published_collection = next(node for node in published.snapshot["nodes"] if node["id"] == "collect")
    assert published_collection["type"] == "data_collection"
    assert {
        "source_node_id": "collect",
        "source_handle": "success",
        "target_node_id": "done",
    }.items() <= published.snapshot["transitions"][0].items()


def test_prompt_is_preserved_in_migration_and_published_snapshot() -> None:
    nodes, edges = _graph()
    migrated = FlowV1ToV2Migrator().migrate_payload(nodes=nodes, edges=edges)
    assert next(node for node in migrated.snapshot['nodes'] if node['id'] == 'collect')['data']['prompt'] == 'Qual é o seu e-mail?'
    published = FlowV2Publisher().publish(nodes=nodes, edges=edges)
    assert next(node for node in published.snapshot['nodes'] if node['id'] == 'collect')['data']['prompt'] == 'Qual é o seu e-mail?'
