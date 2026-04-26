import type { FlowEdgePayload, FlowNodePayload } from '@/lib/types';

type FlowLike = {
  id?: string | null;
  nodes?: unknown;
  edges?: unknown;
} | null | undefined;

export type NormalizedFlowGraph = {
  id: string | null;
  nodes: FlowNodePayload[];
  edges: FlowEdgePayload[];
};

export function normalizeFlow(flow: FlowLike): NormalizedFlowGraph {
  return {
    id: typeof flow?.id === 'string' ? flow.id : null,
    nodes: Array.isArray(flow?.nodes) ? (flow.nodes as FlowNodePayload[]) : [],
    edges: Array.isArray(flow?.edges) ? (flow.edges as FlowEdgePayload[]) : [],
  };
}
