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
  } else if (node.type === 'choice_dynamic' || (node.type === 'choice' && data.options_mode === 'dynamic')) {
    source.clear();
    source.add('default');
  } else if (node.type === 'choice') {
    source.clear();
    const choices = Array.isArray(data.buttons) ? data.buttons : Array.isArray(data.options) ? data.options : [];
    choices.forEach((choice: Record<string, unknown>, index: number) => {
      source.add(builderHandleId(choice.handleId || choice.handle_id || choice.value || choice.id || choice.label, `option_${index + 1}`));
    });
  } else if (node.type === 'data_collection') {
    source.clear();
    DATA_COLLECTION_HANDLES.forEach((handle) => {
      if (handle !== 'invalid' || data.auto_retry_invalid !== true || data.attempts_exceeded_behavior !== 'end') source.add(handle);
    });
  } else if (node.type === 'mcp_tool') {
    source.clear();
    ['success', 'error', 'timeout'].forEach((handle) => source.add(handle));
  }

  return { source, target };
};

/** Validates the persisted edge list without silently dropping stale references. */
export const diagnoseFlowEdges = (nodes: FlowDiagnosticNode[], edges: FlowDiagnosticEdge[]): EdgeDiagnostic[] => {
  const nodesById = new Map(nodes.map((node) => [String(node.id), node]));

  const seenSignatures = new Set<string>();
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
