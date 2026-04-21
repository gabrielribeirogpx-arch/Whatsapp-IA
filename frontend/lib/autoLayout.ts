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
    nodesep: 500,
    ranksep: 700,
    edgesep: 40,
    marginx: 150,
    marginy: 150,
  });

  sortedNodes.forEach((node) => {
    const width = (node.width ?? 320) + 200;
    const height = (node.height ?? 180) + 150;

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

  const childOrderByNodeId = new Map<string, number>();
  const childrenBySource = new Map<string, string[]>();

  sortedEdges.forEach((edge) => {
    const currentChildren = childrenBySource.get(edge.source) ?? [];
    currentChildren.push(edge.target);
    childrenBySource.set(edge.source, currentChildren);
  });

  childrenBySource.forEach((children) => {
    children.forEach((childId, index) => {
      if (!childOrderByNodeId.has(childId)) {
        childOrderByNodeId.set(childId, index);
      }
    });
  });

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    const nodeWidth = node.width ?? defaultNodeWidth;
    const nodeHeight = node.height ?? defaultNodeHeight;
    const childOrder = childOrderByNodeId.get(node.id) ?? 0;

    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2 + childOrder * 220,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
