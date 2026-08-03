<<<<<<< HEAD
import { getCanonicalNodeHandles, normalizeLegacyHandle } from './nodeHandleContract';
=======
import { getNodeHandleContract, normalizeLegacyHandle } from './nodeHandleContract';
>>>>>>> origin/main

export type FlowDiagnosticNode = {
  id: string;
  type?: string | null;
  data?: Record<string, unknown> | null;
};

export type FlowDiagnosticEdge = {
  id?: string | null;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data?: Record<string, unknown> | null;
};

export type EdgeDiagnosticReason =
  | 'source_not_found'
  | 'target_not_found'
  | 'source_handle_not_found'
  | 'target_handle_not_found'
  | 'duplicate_edge'
  | 'self_loop';

export type EdgeDiagnostic = {
  edgeId: string;
  edgeIndex: number;
  source: string;
  target: string;
  handle: string;
  reason: EdgeDiagnosticReason;
};

<<<<<<< HEAD
const normalizeHandle = (value: unknown) => String(value ?? '').trim().toLowerCase();

export const getNodeAvailableHandles = getCanonicalNodeHandles;
=======
export const getNodeAvailableHandles = (node: FlowDiagnosticNode) => {
  const contract = getNodeHandleContract(node);
  return { source: new Set(contract.sourceHandles), target: new Set(contract.targetHandles) };
};
>>>>>>> origin/main

/** Validates the persisted edge list without silently dropping stale references. */
export const diagnoseFlowEdges = (nodes: FlowDiagnosticNode[], edges: FlowDiagnosticEdge[]): EdgeDiagnostic[] => {
  const nodesById = new Map(nodes.map((node) => [String(node.id), node]));

  const seenSignatures = new Set<string>();
  return edges.flatMap((edge, edgeIndex) => {
    const source = String(edge.source || '');
    const target = String(edge.target || '');
    const sourceNode = nodesById.get(source);
    const targetNode = nodesById.get(target);
<<<<<<< HEAD
    const sourceHandle = normalizeLegacyHandle(edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle) || 'default';
    const targetHandle = normalizeLegacyHandle(edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle) || 'default';
=======
    let sourceHandle = normalizeLegacyHandle(edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle);
    let targetHandle = normalizeLegacyHandle(edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle);
    if (!sourceHandle && sourceNode && getNodeHandleContract(sourceNode).sourceHandles.join() === 'default') sourceHandle = 'default';
    if (!targetHandle && targetNode && getNodeHandleContract(targetNode).targetHandles.join() === 'default') targetHandle = 'default';
>>>>>>> origin/main
    const signature = [source, target, sourceHandle, targetHandle].join('\u0000');
    let reason: EdgeDiagnosticReason | null = null;
    let handle = sourceHandle || targetHandle || 'default';

    if (!sourceNode) reason = 'source_not_found';
    else if (!targetNode) reason = 'target_not_found';
    else if (source === target) reason = 'self_loop';
    else if (!getNodeAvailableHandles(sourceNode).source.has(sourceHandle)) {
      reason = 'source_handle_not_found';
      handle = sourceHandle || 'default';
    } else if (!getNodeAvailableHandles(targetNode).target.has(targetHandle)) {
      reason = 'target_handle_not_found';
      handle = targetHandle || 'default';
    } else if (seenSignatures.has(signature)) reason = 'duplicate_edge';

    seenSignatures.add(signature);

    return reason ? [{ edgeId: String(edge.id || `edge-${edgeIndex}`), edgeIndex, source, target, handle, reason }] : [];
  });
};

/** Migrate only named legacy aliases. Missing MCP handles remain missing/default. */
export const migrateLegacyEdgeHandles = <T extends FlowDiagnosticEdge>(edges: T[]): T[] => edges.map((edge) => {
  const rawSource = edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle;
  const rawTarget = edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle;
  const sourceHandle = normalizeLegacyHandle(rawSource);
  const targetHandle = normalizeLegacyHandle(rawTarget);
  if (sourceHandle === normalizeHandle(rawSource) && targetHandle === normalizeHandle(rawTarget)) return edge;
  return { ...edge, ...(sourceHandle ? { sourceHandle } : {}), ...(targetHandle ? { targetHandle } : {}), data: { ...(edge.data || {}), ...(sourceHandle ? { sourceHandle } : {}), ...(targetHandle ? { targetHandle } : {}) } };
});

/**
 * Rebuilds handle availability from the current nodes and returns the same edge
 * array when it is already valid. Keeping this function pure makes it safe for
 * React state setters, hydration, history restoration, paste and publishing.
 */
export const sanitizeEdges = <T extends FlowDiagnosticEdge>(nodes: FlowDiagnosticNode[], edges: T[]): T[] => {
  const invalidIndexes = new Set(diagnoseFlowEdges(nodes, edges).map((issue) => issue.edgeIndex));
  return invalidIndexes.size === 0 ? edges : edges.filter((_, index) => !invalidIndexes.has(index));
};

/** Removes malformed and duplicate node identities before graph serialization. */
export const sanitizeNodes = <T extends FlowDiagnosticNode>(nodes: T[]): T[] => {
  const seen = new Set<string>();
  const sanitized = nodes.filter((node) => {
    const id = String(node?.id || '').trim();
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  return sanitized.length === nodes.length ? nodes : sanitized;
};
