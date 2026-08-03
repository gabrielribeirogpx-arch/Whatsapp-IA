import { DATA_COLLECTION_HANDLES } from './dataCollectionHandles';

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
  | 'duplicate_edge';

export type EdgeDiagnostic = {
  edgeId: string;
  edgeIndex: number;
  source: string;
  target: string;
  handle: string;
  reason: EdgeDiagnosticReason;
};

const normalizeHandle = (value: unknown) => String(value ?? '').trim().toLowerCase();

const builderHandleId = (value: unknown, fallback: string) => {
  const normalized = normalizeHandle(value).replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};

export const getNodeAvailableHandles = (node: FlowDiagnosticNode) => {
  const data = (node.data || {}) as Record<string, any>;
  const source = new Set(['', 'default']);
  const target = new Set(['', 'default']);

  if (node.type === 'condition') {
    source.add('true');
    source.add('false');
  } else if (node.type === 'choice' || node.type === 'choice_dynamic') {
    const choices = Array.isArray(data.buttons) ? data.buttons : Array.isArray(data.options) ? data.options : [];
    choices.forEach((choice: Record<string, unknown>, index: number) => {
      source.add(builderHandleId(choice.handleId || choice.handle_id || choice.value || choice.id || choice.label, `option_${index + 1}`));
    });
  } else if (node.type === 'data_collection') {
    DATA_COLLECTION_HANDLES.forEach((handle) => source.add(handle));
  } else if (node.type === 'mcp_tool') {
    ['success', 'error', 'timeout'].forEach((handle) => source.add(handle));
  }

  return { source, target };
};

/** Validates the persisted edge list without silently dropping stale references. */
export const diagnoseFlowEdges = (nodes: FlowDiagnosticNode[], edges: FlowDiagnosticEdge[]): EdgeDiagnostic[] => {
  const nodesById = new Map(nodes.map((node) => [String(node.id), node]));
  const signatureCounts = new Map<string, number>();

  edges.forEach((edge) => {
    const sourceHandle = edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle;
    const targetHandle = edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle;
    const signature = [edge.source, edge.target, normalizeHandle(sourceHandle), normalizeHandle(targetHandle)].join('\u0000');
    signatureCounts.set(signature, (signatureCounts.get(signature) || 0) + 1);
  });

  return edges.flatMap((edge, edgeIndex) => {
    const source = String(edge.source || '');
    const target = String(edge.target || '');
    const sourceNode = nodesById.get(source);
    const targetNode = nodesById.get(target);
    const sourceHandle = normalizeHandle(edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle);
    const targetHandle = normalizeHandle(edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle);
    const signature = [source, target, sourceHandle, targetHandle].join('\u0000');
    let reason: EdgeDiagnosticReason | null = null;
    let handle = sourceHandle || targetHandle || 'default';

    if (!sourceNode) reason = 'source_not_found';
    else if (!targetNode) reason = 'target_not_found';
    else if (!getNodeAvailableHandles(sourceNode).source.has(sourceHandle)) {
      reason = 'source_handle_not_found';
      handle = sourceHandle || 'default';
    } else if (!getNodeAvailableHandles(targetNode).target.has(targetHandle)) {
      reason = 'target_handle_not_found';
      handle = targetHandle || 'default';
    } else if ((signatureCounts.get(signature) || 0) > 1) reason = 'duplicate_edge';

    return reason ? [{ edgeId: String(edge.id || `edge-${edgeIndex}`), edgeIndex, source, target, handle, reason }] : [];
  });
};
