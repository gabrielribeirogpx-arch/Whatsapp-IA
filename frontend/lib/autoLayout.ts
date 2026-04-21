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
    nodesep: 220,
    ranksep: 320,
    edgesep: 40,
  });

  sortedNodes.forEach((node) => {
    const width = node.width ?? defaultNodeWidth;
    const height = node.height ?? defaultNodeHeight;

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

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const width = node.width ?? defaultNodeWidth;
    const height = node.height ?? defaultNodeHeight;

    return {
      ...node,
      position: {
        x: nodeWithPosition.x - width / 2,
        y: nodeWithPosition.y - height / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
