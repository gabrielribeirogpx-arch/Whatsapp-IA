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
  const edgeData = (edge.data as { sourceHandle?: string } | undefined);
  const candidates = [edge.sourceHandle, edgeData?.sourceHandle]
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

  const choiceSources = new Set(orderedChoiceEdges.keys());
  const nonChoiceEdges = edges.filter((e) => !choiceSources.has(e.source));
  const choiceEdgesOrdered: Edge[] = [];
  orderedChoiceEdges.forEach((sorted) => sorted.forEach((e) => choiceEdgesOrdered.push(e)));

  return [...choiceEdgesOrdered, ...nonChoiceEdges];
}
