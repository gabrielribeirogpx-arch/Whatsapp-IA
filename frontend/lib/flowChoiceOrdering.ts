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

const CHILD_HORIZONTAL_SPACING = 320;
const CHILD_VERTICAL_OFFSET = 220;
const NODE_WIDTH = 260;

export function alignNodes(nodes: Node[], edges: Edge[]): Node[] {
  if (!nodes.length || !edges.length) {
    return nodes;
  }

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const overrides = new Map<string, { x: number; y: number }>();
  const outgoingEdgesBySource = new Map<string, Edge[]>();

  edges.forEach((edge) => {
    const list = outgoingEdgesBySource.get(edge.source) || [];
    list.push(edge);
    outgoingEdgesBySource.set(edge.source, list);
  });

  nodes.forEach((node) => {
    if (node.type !== 'choice') {
      return;
    }

    const buttons = Array.isArray(node.data?.buttons) ? (node.data.buttons as ChoiceOption[]) : [];
    const buttonHandles = buttons
      .map((button) => button.handleId?.toString().trim())
      .filter((handleId): handleId is string => Boolean(handleId));

    if (!buttonHandles.length) {
      return;
    }

    const parentCenterX = node.position.x + NODE_WIDTH / 2;
    const parentY = node.position.y;
    const nodeOutgoingEdges = outgoingEdgesBySource.get(node.id) || [];

    if (!nodeOutgoingEdges.length) {
      return;
    }

    const childrenByHandle = new Map<string, Node>();

    buttonHandles.forEach((handleId) => {
      const matchedEdge = nodeOutgoingEdges.find((edge) => edge.sourceHandle === handleId);
      if (!matchedEdge) return;
      const child = nodeMap.get(matchedEdge.target);
      if (!child) return;
      childrenByHandle.set(handleId, child);
    });

    const orderedChildren = buttonHandles
      .map((handleId) => childrenByHandle.get(handleId) || null)
      .filter((child): child is Node => Boolean(child));

    if (!orderedChildren.length) {
      return;
    }

    const alreadyOrderedIds = new Set(orderedChildren.map((child) => child.id));
    const remainingChildren = nodeOutgoingEdges
      .map((edge) => nodeMap.get(edge.target) || null)
      .filter((child): child is Node => Boolean(child) && !alreadyOrderedIds.has(child.id));

    const finalChildren = [...orderedChildren, ...remainingChildren];

    const totalWidth = (finalChildren.length - 1) * CHILD_HORIZONTAL_SPACING;
    const startX = parentCenterX - totalWidth / 2 - NODE_WIDTH / 2;
    const childY = parentY + CHILD_VERTICAL_OFFSET;

    finalChildren.forEach((child, index) => {
      overrides.set(child.id, {
        x: startX + index * CHILD_HORIZONTAL_SPACING,
        y: childY,
      });
    });
  });

  return nodes.map((node) => {
    const nextPosition = overrides.get(node.id);
    if (!nextPosition) {
      return node;
    }
    const { x, y } = nextPosition;

    return {
      ...node,
      position: { x, y },
      positionAbsolute: { x, y },
    };
  });
}

export const alignChoiceChildren = alignNodes;
