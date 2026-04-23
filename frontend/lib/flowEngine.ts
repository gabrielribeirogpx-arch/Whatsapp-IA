export type FlowNode = {
  id: string;
  type: string;
  data?: any;
};

export type FlowEdge = {
  id?: string;
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
  | { type: 'waiting_input'; nodeId: string }
  | { type: 'condition'; result: 'true' | 'false'; trueNodeId?: string; falseNodeId?: string }
  | { type: 'delay'; seconds: number; nextNodeId?: string }
  | { type: 'action'; actionName: string; nextNodeId?: string }
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
  context?: { lastUserMessage?: string }
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

  // CONDITION — se não há lastUserMessage, para e aguarda input do usuário
  if (node.type === 'condition') {
    const keyword = (node.data?.condition || '').toLowerCase().trim();
    const lastMessage = (context?.lastUserMessage || '').toLowerCase().trim();

    // Sem mensagem do usuário ainda — para o fluxo e aguarda input
    if (!lastMessage) {
      return { type: 'waiting_input', nodeId: node.id };
    }

    const matched = keyword.length > 0 && lastMessage.includes(keyword);
    const result = matched ? 'true' : 'false';

    const trueNodeId = getNextNodeByHandle(node.id, 'true', flow.edges) || undefined;
    const falseNodeId = getNextNodeByHandle(node.id, 'false', flow.edges) || undefined;

    return { type: 'condition', result, trueNodeId, falseNodeId };
  }

  // DELAY
  if (node.type === 'delay') {
    const seconds = parseFloat(node.data?.content || node.data?.text || '3') || 3;
    const next = getNextNode(node.id, flow.edges);
    return {
      type: 'delay',
      seconds,
      nextNodeId: next || undefined,
    };
  }

  // ACTION — executa silenciosamente, sem gerar mensagem no chat
  if (node.type === 'action') {
    const next = getNextNode(node.id, flow.edges);
    return {
      type: 'action',
      actionName: node.data?.action || '',
      nextNodeId: next || undefined,
    };
  }

  return { type: 'end' };
}

export function handleUserChoice(
  flow: Flow,
  currentNodeId: string,
  handleId: string,
  context?: { lastUserMessage?: string }
): FlowResponse {
  const nextNodeId = getNextNodeByHandle(currentNodeId, handleId, flow.edges);
  if (!nextNodeId) {
    return { type: 'end' };
  }
  return executeNode(flow, nextNodeId, context);
}
