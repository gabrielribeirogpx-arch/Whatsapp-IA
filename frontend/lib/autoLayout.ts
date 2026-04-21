import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const defaultNodeWidth = 340;
const defaultNodeHeight = 200;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  const sortedNodes = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const sortedEdges = [...edges].sort((a, b) =>
    `${a.source}${a.target}`.localeCompare(`${b.source}${b.target}`),
  );

  dagreGraph.setGraph({
    rankdir: 'LR',
    nodesep: 300,
    ranksep: 420,
    edgesep: 40,
    marginx: 80,
    marginy: 80,
  });

  sortedNodes.forEach((node) => {
    const width = (node.width ?? 320) + 120;
    const height = (node.height ?? 180) + 80;

    dagreGraph.setNode(node.id, {
      width,
      height,
    });
  });

  sortedEdges.forEach((edge, index) => {
    dagreGraph.setEdge(edge.source, edge.target, {
      weight: index,
    });
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node, index) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const nodeWidth = node.width ?? defaultNodeWidth;
    const nodeHeight = node.height ?? defaultNodeHeight;

    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2 + index * 40,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
