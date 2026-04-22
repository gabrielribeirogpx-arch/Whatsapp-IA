import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const nodeWidth = 260;
const nodeHeight = 140;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 200 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const positionMap = new Map<string, { x: number; y: number }>();
  nodes.forEach((node) => {
    const n = dagreGraph.node(node.id);
    positionMap.set(node.id, {
      x: n.x - nodeWidth / 2,
      y: n.y - nodeHeight / 2,
    });
  });

  // Centraliza cada node "choice" no eixo Y em relação aos seus filhos
  nodes
    .filter((n) => n.type === 'choice')
    .forEach((choiceNode) => {
      const childEdges = edges.filter((e) => e.source === choiceNode.id);
      const childPositions = childEdges
        .map((e) => positionMap.get(e.target))
        .filter((p): p is { x: number; y: number } => Boolean(p));

      if (!childPositions.length) return;

      const minY = Math.min(...childPositions.map((p) => p.y));
      const maxY = Math.max(...childPositions.map((p) => p.y));
      const centerY = (minY + maxY) / 2;

      const current = positionMap.get(choiceNode.id);
      if (current) {
        positionMap.set(choiceNode.id, {
          x: current.x,
          y: centerY - nodeHeight / 2,
        });
      }
    });

  const layoutedNodes = nodes.map((node) => {
    const pos = positionMap.get(node.id);
    if (!pos) return node;
    return { ...node, position: pos };
  });

  return { nodes: layoutedNodes, edges };
}
