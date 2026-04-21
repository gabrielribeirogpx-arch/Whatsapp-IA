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
    .replace(/\s+/g, '_');

const extractChoiceOrder = (node: Node) => {
  const options = Array.isArray(node.data?.options) ? (node.data.options as string[]) : [];
  const buttons = Array.isArray(node.data?.buttons) ? (node.data.buttons as ChoiceOption[]) : [];

  const optionValues = options.length > 0
    ? options
    : buttons.map((button) => button.label || button.handleId || '');

  return optionValues
    .map((option) => normalizeValue(option))
    .filter(Boolean);
};

const getEdgeOptionValue = (edge: Edge) =>
  normalizeValue(
    (edge.data as { option?: string; condition?: string; sourceHandle?: string } | undefined)?.option ||
    edge.label?.toString() ||
    edge.sourceHandle ||
    (edge.data as { condition?: string; sourceHandle?: string } | undefined)?.condition ||
    (edge.data as { sourceHandle?: string } | undefined)?.sourceHandle,
  );

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

    const orderIndex = new Map(order.map((value, index) => [value, index]));

    const sorted = choiceEdges
      .map((edge, index) => ({
        edge,
        index,
        optionIndex: orderIndex.get(getEdgeOptionValue(edge)) ?? Number.MAX_SAFE_INTEGER,
      }))
      .sort((a, b) => {
        if (a.optionIndex !== b.optionIndex) {
          return a.optionIndex - b.optionIndex;
        }

        return a.index - b.index;
      })
      .map((item) => item.edge);

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
