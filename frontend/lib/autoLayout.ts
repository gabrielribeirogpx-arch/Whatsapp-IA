import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const nodeWidth = 260;
const nodeHeight = 140;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  // Identifica filhos diretos de nodes "choice"
  const choiceNodeIds = new Set(
    nodes.filter((n) => n.type === 'choice').map((n) => n.id)
  );
  const choiceChildIds = new Set(
    edges
      .filter((e) => choiceNodeIds.has(e.source))
      .map((e) => e.target)
  );

  // Roda dagre apenas nos nodes que NÃO são filhos de choice
  const dagreNodes = nodes.filter((n) => !choiceChildIds.has(n.id));

  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 120 });

  dagreNodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    // só adiciona edge se ambos os endpoints estão no grafo dagre
    if (!choiceChildIds.has(edge.source) && !choiceChildIds.has(edge.target)) {
      dagreGraph.setEdge(edge.source, edge.target);
    }
  });

  dagre.layout(dagreGraph);

  // Posições calculadas pelo dagre
  const positionMap = new Map<string, { x: number; y: number }>();
  dagreNodes.forEach((node) => {
    const n = dagreGraph.node(node.id);
    positionMap.set(node.id, {
      x: n.x - nodeWidth / 2,
      y: n.y - nodeHeight / 2,
    });
  });

  // Posiciona filhos de choice manualmente
  nodes
    .filter((n) => n.type === 'choice')
    .forEach((choiceNode) => {
      const buttons: Array<{ handleId?: string }> =
        Array.isArray(choiceNode.data?.buttons) ? choiceNode.data.buttons : [];

      const childrenOrdered = buttons
        .map((btn) => {
          const edge = edges.find(
            (e) => e.source === choiceNode.id && e.sourceHandle === btn.handleId
          );
          return edge ? nodes.find((n) => n.id === edge.target) ?? null : null;
        })
        .filter((n): n is Node => n !== null);

      if (!childrenOrdered.length) return;

      const parentPos = positionMap.get(choiceNode.id);
      if (!parentPos) return;

      const parentCenterX = parentPos.x + nodeWidth / 2;
      const totalWidth = childrenOrdered.length * nodeWidth +
        (childrenOrdered.length - 1) * 80;
      const startX = parentCenterX - totalWidth / 2;
      const childY = parentPos.y + nodeHeight + 80;

      childrenOrdered.forEach((child, i) => {
        positionMap.set(child.id, {
          x: startX + i * (nodeWidth + 80),
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
