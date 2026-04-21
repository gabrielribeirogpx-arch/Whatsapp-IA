import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const nodeWidth = 260;
const nodeHeight = 140;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 120 });

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

  nodes
    .filter((n) => n.type === 'choice')
    .forEach((choiceNode) => {
      const buttons: Array<{ handleId?: string }> = Array.isArray(choiceNode.data?.buttons)
        ? (choiceNode.data.buttons as Array<{ handleId?: string }>)
        : [];

      const childEdges = edges.filter((e) => e.source === choiceNode.id);
      if (!childEdges.length) return;

      const orderedChildren: Node[] = buttons
        .map((btn) => {
          const edge = childEdges.find((e) => {
            const sh =
              e.sourceHandle ??
              (e.data as { sourceHandle?: string } | undefined)?.sourceHandle ??
              '';
            return sh === btn.handleId;
          });
          return edge ? (nodes.find((n) => n.id === edge.target) ?? null) : null;
        })
        .filter((n): n is Node => n !== null);

      const fallbackChildren: Node[] = childEdges
        .map((e) => nodes.find((n) => n.id === e.target) ?? null)
        .filter((n): n is Node => n !== null);

      const children = orderedChildren.length > 0 ? orderedChildren : fallbackChildren;
      if (!children.length) return;

      const parentPos = positionMap.get(choiceNode.id);
      if (!parentPos) return;

      const SPACING = 80;
      const parentCenterX = parentPos.x + nodeWidth / 2;
      const totalWidth = children.length * nodeWidth + (children.length - 1) * SPACING;
      const startX = parentCenterX - totalWidth / 2;
      const childY = parentPos.y + nodeHeight + 80;

      children.forEach((child, i) => {
        positionMap.set(child.id, {
          x: startX + i * (nodeWidth + SPACING),
          y: childY,
        });
      });
    });

  const layoutedNodes = nodes.map((node) => {
    const pos = positionMap.get(node.id);
    if (!pos) return node;
    return { ...node, position: pos };
  });

  return { nodes: layoutedNodes, edges };
}
