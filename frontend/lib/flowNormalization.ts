import type { FlowEdgePayload, FlowNodePayload } from '@/lib/types';

type FlowLike = {
  id?: string | null;
  nodes?: unknown;
  edges?: unknown;
  raw_nodes?: unknown;
  raw_edges?: unknown;
  current_version?: {
    nodes?: unknown;
    edges?: unknown;
  } | null;
} | null | undefined;

export type NormalizedFlowGraph = {
  id: string | null;
  nodes: FlowNodePayload[];
  edges: FlowEdgePayload[];
};

const normalizeNode = (node: unknown): FlowNodePayload => {
  const safeNode = (node && typeof node === 'object' ? node : {}) as Record<string, unknown>;
  const nodeData = (safeNode.data && typeof safeNode.data === 'object' ? safeNode.data : {}) as FlowNodePayload['data'];

  return {
    id: String(safeNode.id ?? ''),
    type: String(safeNode.type ?? 'message'),
    data: nodeData,
    position:
      safeNode.position && typeof safeNode.position === 'object'
        ? (safeNode.position as { x: number; y: number })
        : { x: 0, y: 0 },
  };
};

export function normalizeFlow(flow: FlowLike): NormalizedFlowGraph {
  const directNodes = Array.isArray(flow?.nodes) ? (flow.nodes as unknown[]) : [];
  const directEdges = Array.isArray(flow?.edges) ? (flow.edges as FlowEdgePayload[]) : [];
  const versionNodes = Array.isArray(flow?.current_version?.nodes) ? (flow.current_version?.nodes as unknown[]) : [];
  const versionEdges = Array.isArray(flow?.current_version?.edges) ? (flow.current_version?.edges as FlowEdgePayload[]) : [];
  const persistedNodes = Array.isArray(flow?.raw_nodes) ? (flow.raw_nodes as unknown[]) : [];
  const persistedEdges = Array.isArray(flow?.raw_edges) ? (flow.raw_edges as FlowEdgePayload[]) : [];

  const selectedNodes =
    versionNodes.length > 1
      ? versionNodes
      : directNodes.length > 0
      ? directNodes
      : persistedNodes;

  const selectedEdges =
    versionEdges.length > 0
      ? versionEdges
      : directEdges.length > 0
      ? directEdges
      : persistedEdges;

  return {
    id: typeof flow?.id === 'string' ? flow.id : null,
    nodes: selectedNodes.map(normalizeNode),
    edges: selectedEdges,
  };
}
