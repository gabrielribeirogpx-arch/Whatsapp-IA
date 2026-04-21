import dagre from 'dagre';
import type { Edge, Node } from 'reactflow';

const nodeWidth = 260;
const nodeHeight = 140;

export function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  dagreGraph.setGraph({
    rankdir: 'LR',
    nodesep: 80,
    ranksep: 120,
  });

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const choiceChildIds = new Set<string>();
  const choiceChildrenByParent = new Map<string, string[]>();

  edges.forEach((edge) => {
    const sourceNode = nodeById.get(edge.source);
    if (sourceNode?.type !== 'choice') {
      return;
    }

    choiceChildIds.add(edge.target);
    const children = choiceChildrenByParent.get(edge.source) || [];
    children.push(edge.target);
    choiceChildrenByParent.set(edge.source, children);
  });

  nodes.forEach((node) => {
    if (choiceChildIds.has(node.id)) {
      return;
    }

    dagreGraph.setNode(node.id, {
      width: nodeWidth,
      height: nodeHeight,
    });
  });

  edges.forEach((edge) => {
    if (choiceChildIds.has(edge.source) || choiceChildIds.has(edge.target)) {
      return;
    }

    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    if (choiceChildIds.has(node.id)) {
      return node;
    }

    const nodeWithPosition = dagreGraph.node(node.id);

    return {
      ...node,
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
    };
  });

  const layoutedNodeMap = new Map(layoutedNodes.map((node) => [node.id, node]));
  const manualChoiceChildPositions = new Map<string, { x: number; y: number }>();

  choiceChildrenByParent.forEach((children, parentId) => {
    const parentNode = layoutedNodeMap.get(parentId);
    if (!parentNode) {
      return;
    }

    const uniqueChildren = Array.from(new Set(children));
    if (!uniqueChildren.length) {
      return;
    }

    const parentCenterX = parentNode.position.x + nodeWidth / 2;
    const startX = parentCenterX - ((uniqueChildren.length - 1) * nodeWidth) / 2;
    const childY = parentNode.position.y + nodeHeight + 80;

    uniqueChildren.forEach((childId, index) => {
      manualChoiceChildPositions.set(childId, {
        x: startX + index * nodeWidth - nodeWidth / 2,
        y: childY,
      });
    });
  });

  const nodesWithManualChoiceChildren = layoutedNodes.map((node) => {
    const manualPosition = manualChoiceChildPositions.get(node.id);
    if (!manualPosition) {
      return node;
    }

    return {
      ...node,
      position: manualPosition,
      positionAbsolute: manualPosition,
    };
  });

  return { nodes: nodesWithManualChoiceChildren, edges };
}
