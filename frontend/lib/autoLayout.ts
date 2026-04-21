import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const nodeWidth = 260;
const nodeHeight = 140;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  const nodeOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const sortedNodes = [...nodes].sort(
    (a, b) => (nodeOrder.get(a.id) ?? 0) - (nodeOrder.get(b.id) ?? 0),
  );

  dagreGraph.setGraph({
    rankdir: 'LR',
    nodesep: 80,
    ranksep: 120,
  });

  sortedNodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: nodeWidth,
      height: nodeHeight,
    });
  });

  edges.forEach((edge, index) => {
    dagreGraph.setEdge(edge.source, edge.target, {
      weight: index,
    });
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);

    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
