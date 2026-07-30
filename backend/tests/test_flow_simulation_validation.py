from app.services.flow_engine_service import validate_flow_graph


def node(node_id, *, start=False, final=False, node_type="message"):
    return {
        "id": node_id,
        "type": node_type,
        "data": {"text": node_id, "isStart": start, "isFinal": final},
    }


def test_simulate_valid_flow_without_orphans():
    result = validate_flow_graph(
        [node("start", start=True), node("end", final=True)],
        [{"source": "start", "target": "end"}],
        mode="simulate",
    )
    assert result == {"valid": True, "errors": [], "warnings": []}


def test_simulate_ignores_orphan_without_output_with_warning():
    result = validate_flow_graph(
        [node("start", start=True), node("end", final=True), node("draft")],
        [{"source": "start", "target": "end"}],
        mode="simulate",
    )
    assert result["valid"] is True
    assert result["errors"] == []
    assert [(item["code"], item["node_id"]) for item in result["warnings"]] == [("ORPHAN_NODE", "draft")]


def test_simulate_blocks_reachable_non_terminal_without_output():
    result = validate_flow_graph(
        [node("start", start=True), node("transfer", node_type="message")],
        [{"source": "start", "target": "transfer"}],
        mode="simulate",
    )
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "NODE_WITHOUT_OUTPUT"
    assert result["errors"][0]["node_id"] == "transfer"


def test_simulate_allows_reachable_final_without_output():
    result = validate_flow_graph([node("start", start=True, final=True)], [], mode="simulate")
    assert result["valid"] is True


def test_publish_remains_strict_for_orphans():
    result = validate_flow_graph(
        [node("start", start=True, final=True), node("draft")], [], mode="publish"
    )
    assert any(item["code"] == "ORPHAN_NODE" for item in result["errors"])
