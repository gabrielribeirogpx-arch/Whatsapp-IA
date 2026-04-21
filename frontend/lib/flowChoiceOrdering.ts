import type { Edge, Node } from 'reactflow';

type ChoiceOption = {
  label?: string;
  handleId?: string;
};

const normalizeValue = (value?: string | null) =>
  (value || '')
    .toString()
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s_]/g, '')
    .replace(/\s+/g, '_');

const extractChoiceOrder = (node: Node) => {
  const options = Array.isArray(node.data?.options) ? (node.data.options as string[]) : [];
  const buttons = Array.isArray(node.data?.buttons) ? (node.data.buttons as ChoiceOption[]) : [];

  const optionValues = options.length > 0
    ? options
    : buttons.map((button) => button.label || button.handleId || '');

  const normalized = optionValues
    .map((option) => normalizeValue(option))
    .filter(Boolean);

  return Array.from(new Set(normalized));
};

const getEdgeOptionCandidates = (edge: Edge) => {
  const edgeData = (edge.data as { option?: string; condition?: string; sourceHandle?: string } | undefined);
  const candidates = [
    edgeData?.option,
    edge.label?.toString(),
    edge.sourceHandle,
    edgeData?.condition,
    edgeData?.sourceHandle,
  ]
    .map((value) => normalizeValue(value))
    .filter(Boolean);

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

const CHILD_VERTICAL_SPACING = 120;

const extractOptionHandleOrder = (node: Node) => {
  const options = Array.isArray(node.data?.options) ? (node.data.options as string[]) : [];
  return options
    .map((option) => normalizeValue(option))
    .filter(Boolean);
};

export function forceChoiceChildrenYOrder(nodes: Node[], edges: Edge[]): Node[] {
  if (!nodes.length || !edges.length) {
    return nodes;
  }

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const nextNodes = nodes.map((node) => ({ ...node, position: { ...node.position } }));

  nextNodes.forEach((node) => {
    if (node.type !== 'choice') {
      return;
    }

    const optionOrder = extractOptionHandleOrder(node);
    if (optionOrder.length === 0) {
      return;
    }

    const orderedChildren = optionOrder
      .map((optionHandle) => {
        const edge = edges.find((currentEdge) =>
          currentEdge.source === node.id && normalizeValue(currentEdge.sourceHandle || '') === optionHandle,
        );

        if (!edge) {
          return null;
        }

        return nodeMap.get(edge.target) || null;
      })
      .filter((child): child is Node => Boolean(child));

    if (orderedChildren.length === 0) {
      return;
    }

    const startY = node.position.y - ((optionOrder.length - 1) * CHILD_VERTICAL_SPACING) / 2;

    orderedChildren.forEach((child, index) => {
      const childToUpdate = nextNodes.find((currentNode) => currentNode.id === child.id);
      if (!childToUpdate) {
        return;
      }

      childToUpdate.position.y = startY + index * CHILD_VERTICAL_SPACING;
    });
  });

  return nextNodes;
}
