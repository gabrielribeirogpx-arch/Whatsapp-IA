export type FlowNode = {
  id: string;
  type: string;
  data?: any;
};

export type FlowEdge = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  data?: {
    sourceHandle?: string;
  };
};

export type Flow = {
  nodes: FlowNode[];
  edges: FlowEdge[];
};

export type FlowResponse =
  | { type: 'message'; text: string; nextNodeId?: string }
  | { type: 'choice'; text: string; buttons: any[] }
  | { type: 'system'; nextNodeId?: string }
  | { type: 'end' };

function getOutgoingEdges(nodeId: string, edges: FlowEdge[]) {
  return edges.filter((e) => e.source === nodeId);
}

function resolveHandle(edge: FlowEdge): string | null {
  return edge.sourceHandle ?? edge.data?.sourceHandle ?? null;
}

function getNextNode(nodeId: string, edges: FlowEdge[]): string | null {
  const outgoing = getOutgoingEdges(nodeId, edges);
  if (!outgoing.length) return null;
  return outgoing[0].target;
}

function getNextNodeByHandle(
  nodeId: string,
  handleId: string,
  edges: FlowEdge[]
): string | null {
  const outgoing = getOutgoingEdges(nodeId, edges);

  const match = outgoing.find((e) => {
    const h = resolveHandle(e);
    return h === handleId;
  });

  return match ? match.target : null;
}

export function executeNode(
  flow: Flow,
  currentNodeId: string,
  input?: { handleId?: string }
): FlowResponse {
  const node = flow.nodes.find((n) => n.id === currentNodeId);

  if (!node) {
    return { type: 'end' };
  }

  // MESSAGE
  if (node.type === 'message') {
    const next = getNextNode(node.id, flow.edges);

    return {
      type: 'message',
      text: node.data?.content || node.data?.text || node.data?.label || '',
      nextNodeId: next || undefined,
    };
  }

  // CHOICE
  if (node.type === 'choice') {
    return {
      type: 'choice',
      text: node.data?.content || node.data?.text || node.data?.label || '',
      buttons: node.data?.buttons || [],
    };
  }

  // CONDITION (interno)
  if (node.type === 'condition') {
    const trueId = getNextNodeByHandle(node.id, 'true', flow.edges);
    const falseId = getNextNodeByHandle(node.id, 'false', flow.edges);
    const fallbackNext = getNextNode(node.id, flow.edges);
    const result = Boolean(node.data?.result);

    return {
      type: 'system',
      nextNodeId: (result ? trueId : falseId) || fallbackNext || undefined,
    };
  }

  // DELAY (interno)
  if (node.type === 'delay') {
    const next = getNextNode(node.id, flow.edges);

    return {
      type: 'system',
      nextNodeId: next || undefined,
    };
  }

  // ACTION (interno)
  if (node.type === 'action') {
    const next = getNextNode(node.id, flow.edges);

    return {
      type: 'system',
      nextNodeId: next || undefined,
    };
  }

  return { type: 'end' };
}

export function handleUserChoice(
  flow: Flow,
  currentNodeId: string,
  handleId: string
): FlowResponse {
  const nextNodeId = getNextNodeByHandle(currentNodeId, handleId, flow.edges);

  if (!nextNodeId) {
    return { type: 'end' };
  }

  return executeNode(flow, nextNodeId);
}
