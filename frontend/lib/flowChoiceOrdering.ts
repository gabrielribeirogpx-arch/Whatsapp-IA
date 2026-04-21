import type { Edge, Node } from 'reactflow';

type ChoiceOption = {
  handleId?: string;
};

const extractChoiceOrder = (node: Node) => {
  const buttons = Array.isArray(node.data?.buttons) ? (node.data.buttons as ChoiceOption[]) : [];
  return buttons
    .map((button) => button.handleId)
    .filter((handleId): handleId is string => Boolean(handleId));
};

const getEdgeOptionCandidates = (edge: Edge) => {
  const candidates = [edge.sourceHandle]
    .map((value) => value?.toString().trim())
    .filter((value): value is string => Boolean(value));

  return Array.from(new Set(candidates));
};

export function orderChoiceChildrenEdges(nodes: Node[], edges: Edge[]): Edge[] {
  if (!nodes.length || !edges.length) {
    return edges;
  }

  const edgesByChoiceNode = new Map<string, Edge[]>();
  const choiceOrderByNode = new Map<string, string[]>();

  nodes.forEach((node) => {
    if (node.type !== 'choice') {
      return;
    }

    const order = extractChoiceOrder(node);
    if (order.length > 0) {
      choiceOrderByNode.set(node.id, order);
      edgesByChoiceNode.set(node.id, []);
    }
  });

  if (choiceOrderByNode.size === 0) {
    return edges;
  }

  edges.forEach((edge) => {
    const choiceEdges = edgesByChoiceNode.get(edge.source);
    if (choiceEdges) {
      choiceEdges.push(edge);
    }
  });

  const orderedChoiceEdges = new Map<string, Edge[]>();

  edgesByChoiceNode.forEach((choiceEdges, nodeId) => {
    const order = choiceOrderByNode.get(nodeId);
    if (!order || choiceEdges.length < 2) {
      return;
    }

    const usedEdgeIds = new Set<string>();
    const sorted: Edge[] = [];

    order.forEach((optionKey) => {
      const matchedEdge = choiceEdges.find((edge) => {
        if (usedEdgeIds.has(edge.id)) {
          return false;
        }

        const candidates = getEdgeOptionCandidates(edge);
        return candidates.includes(optionKey);
      });

      if (matchedEdge) {
        usedEdgeIds.add(matchedEdge.id);
        sorted.push(matchedEdge);
      }
    });

    choiceEdges.forEach((edge) => {
      if (!usedEdgeIds.has(edge.id)) {
        sorted.push(edge);
      }
    });

    orderedChoiceEdges.set(nodeId, sorted);
  });

  if (orderedChoiceEdges.size === 0) {
    return edges;
  }

  const nextEdgeIndex = new Map<string, number>();

  return edges.map((edge) => {
    const sorted = orderedChoiceEdges.get(edge.source);
    if (!sorted) {
      return edge;
    }

    const index = nextEdgeIndex.get(edge.source) || 0;
    nextEdgeIndex.set(edge.source, index + 1);
    return sorted[index] || edge;
  });
}

const CHILD_HORIZONTAL_SPACING = 180;
const CHILD_VERTICAL_OFFSET = 200;

export function alignNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (!nodes.length) {
    return nodes;
  }

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const updated = [...nodes];

  console.log('ALIGN DEBUG', {
    edges: edges.map((edge) => edge.sourceHandle),
    buttons: nodes.find((node) => node.type === 'choice')?.data?.buttons?.map((button: ChoiceOption) => button.handleId),
  });

  nodes.forEach((node) => {
    if (node.type !== 'choice') {
      return;
    }

    const options = Array.isArray(node.data?.buttons)
      ? (node.data.buttons as ChoiceOption[])
        .map((button) => button.handleId?.toString().trim())
        .filter((handleId): handleId is string => Boolean(handleId))
      : [];
    const parentX = node.position.x;
    const parentY = node.position.y;

    const children = options
      .map((handleId) => {
        const edge = edges.find((currentEdge) => currentEdge.source === node.id && currentEdge.sourceHandle === handleId);
        return edge ? nodeMap.get(edge.target) || null : null;
      })
      .filter((child): child is Node => Boolean(child));

    const startX = parentX - ((children.length - 1) * CHILD_HORIZONTAL_SPACING) / 2;

    children.forEach((child, index) => {
      const updatedIndex = updated.findIndex((currentNode) => currentNode.id === child.id);
      if (updatedIndex === -1) return;
      const x = startX + index * CHILD_HORIZONTAL_SPACING;
      const y = parentY + CHILD_VERTICAL_OFFSET;
      updated[updatedIndex] = {
        ...updated[updatedIndex],
        position: { x, y },
        positionAbsolute: { x, y },
      };
    });
  });

  return updated;
}

export const alignChoiceChildren = alignNodes;
