from __future__ import annotations

from app.debugger.execution_serializer import ReplayEdge, ReplayEvent, ReplayNode


class ExecutionGraphBuilder:
    """Build a navigable graph from replay nodes without altering runtime traces."""

    def build(self, nodes: list[ReplayNode], timeline: list[ReplayEvent]) -> dict[str, list]:
        return {"nodes": nodes, "edges": self.build_edges(nodes), "timeline": timeline}

    def build_edges(self, nodes: list[ReplayNode]) -> list[ReplayEdge]:
        edges: list[ReplayEdge] = []
        previous_by_execution: dict[str, ReplayNode] = {}
        for index, node in enumerate(nodes):
            execution_key = node.execution_id or "__default__"
            previous = previous_by_execution.get(execution_key)
            if previous and previous.node_id != node.node_id:
                edges.append(
                    ReplayEdge(
                        source=previous.node_id,
                        target=node.node_id,
                        highlighted=True,
                        execution_id=node.execution_id,
                        order=index,
                    )
                )
            previous_by_execution[execution_key] = node
        return edges

    def get_execution_path(self, nodes: list[ReplayNode]) -> list[str]:
        return [node.node_id for node in nodes]
