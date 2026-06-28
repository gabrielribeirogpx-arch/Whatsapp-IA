import type { FlowEdgePayload, FlowNodePayload } from '@/lib/types';

type FlowLike = {
  id?: string | null;
  nodes?: unknown;
  edges?: unknown;
  raw_nodes?: unknown;
  raw_edges?: unknown;
  editor_graph?: {
    nodes?: unknown;
    edges?: unknown;
  } | null;
  runtime_graph?: {
    nodes?: unknown;
    edges?: unknown;
  } | null;
  published_snapshot_graph?: {
    nodes?: unknown;
    edges?: unknown;
  } | null;
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

const rowsToButtons = (nodeId: string, sections: unknown): Array<{ id: string; label: string; handleId: string }> => {
  if (!Array.isArray(sections)) return [];

  return sections.flatMap((section, sectionIndex) => {
    if (!section || typeof section !== 'object') return [];
    const rows = Array.isArray((section as { rows?: unknown }).rows) ? ((section as { rows: unknown[] }).rows) : [];
    return rows.flatMap((row, rowIndex) => {
      if (!row || typeof row !== 'object') return [];
      const safeRow = row as Record<string, unknown>;
      const label = String(safeRow.label ?? safeRow.title ?? `Opção ${rowIndex + 1}`);
      const handleId = String(safeRow.handleId ?? safeRow.handle_id ?? safeRow.id ?? `option_${sectionIndex + 1}_${rowIndex + 1}`);
      return [{ id: String(safeRow.id ?? `${nodeId}-row-${sectionIndex + 1}-${rowIndex + 1}`), label, handleId }];
    });
  });
};

const parseDelaySeconds = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

type DelayNodeInput = FlowNodePayload & {
  delay_seconds?: unknown;
  wait_seconds?: unknown;
  duration?: unknown;
  value?: unknown;
  delay?: unknown;
};

const normalizeDelayNode = (node: FlowNodePayload): FlowNodePayload => {
  if (node.type !== 'delay') return node;
  const data = (node.data || {}) as Record<string, unknown>;
  const delayNode = node as DelayNodeInput;
  const seconds = parseDelaySeconds(
    delayNode.seconds ??
    data.seconds ??
    data.content ??
    data.delay ??
    data.wait_seconds ??
    data.duration ??
    delayNode.delay_seconds ??
    delayNode.wait_seconds ??
    delayNode.duration ??
    delayNode.value ??
    delayNode.delay,
  );
  const { content, delay, wait_seconds, duration, seconds: _dataSeconds, ...cleanData } = data;
  return {
    ...node,
    type: 'delay',
    ...(seconds !== undefined ? { seconds } : {}),
    data: {
      ...(cleanData as FlowNodePayload['data']),
      ...(seconds !== undefined ? { seconds } : {}),
    },
  };
};

const normalizeNode = (node: unknown): FlowNodePayload => {
  const safeNode = (node && typeof node === 'object' ? node : {}) as Record<string, unknown>;
  const nodeData = (safeNode.data && typeof safeNode.data === 'object' ? safeNode.data : {}) as FlowNodePayload['data'] & Record<string, unknown>;
  const nodeId = String(safeNode.id ?? '');
  const rawType = String(safeNode.type ?? 'message').toLowerCase();
  const isLegacyButtons = rawType === 'buttons' || rawType === 'buttons_node';
  const isLegacyList = rawType === 'list' || rawType === 'list_node';
  const data = isLegacyButtons
    ? { ...nodeData, display_mode: 'buttons' as const, content: String(nodeData.content ?? nodeData.body_text ?? '') }
    : isLegacyList
    ? { ...nodeData, display_mode: 'list' as const, content: String(nodeData.content ?? nodeData.body_text ?? ''), buttons: nodeData.buttons ?? rowsToButtons(nodeId, nodeData.sections) }
    : nodeData;

  const normalizedType = isLegacyButtons || isLegacyList ? 'choice' : String(safeNode.type ?? 'message');
  const topLevelDelaySeconds = parseDelaySeconds(
    safeNode.seconds ??
    safeNode.delay_seconds ??
    safeNode.wait_seconds ??
    safeNode.duration ??
    safeNode.value ??
    safeNode.delay,
  );

  return normalizeDelayNode({
    id: nodeId,
    type: normalizedType,
    ...(normalizedType === 'delay' && topLevelDelaySeconds !== undefined ? { seconds: topLevelDelaySeconds } : {}),
    data,
    position:
      safeNode.position && typeof safeNode.position === 'object'
        ? (safeNode.position as { x: number; y: number })
        : { x: 0, y: 0 },
  });
};

export function normalizeFlow(flow: FlowLike): NormalizedFlowGraph {
  const editorNodes = Array.isArray(flow?.editor_graph?.nodes) ? (flow.editor_graph.nodes as unknown[]) : [];
  const editorEdges = Array.isArray(flow?.editor_graph?.edges) ? (flow.editor_graph.edges as FlowEdgePayload[]) : [];
  const directNodes = Array.isArray(flow?.nodes) ? (flow.nodes as unknown[]) : [];
  const directEdges = Array.isArray(flow?.edges) ? (flow.edges as FlowEdgePayload[]) : [];
  const versionNodes = Array.isArray(flow?.current_version?.nodes) ? (flow.current_version?.nodes as unknown[]) : [];
  const versionEdges = Array.isArray(flow?.current_version?.edges) ? (flow.current_version?.edges as FlowEdgePayload[]) : [];
  const persistedNodes = Array.isArray(flow?.raw_nodes) ? (flow.raw_nodes as unknown[]) : [];
  const persistedEdges = Array.isArray(flow?.raw_edges) ? (flow.raw_edges as FlowEdgePayload[]) : [];

  const selectedNodes =
    editorNodes.length > 0
      ? editorNodes
      : persistedNodes.length > 0
      ? persistedNodes
      : directNodes.length > 0
      ? directNodes
      : versionNodes;

  const selectedEdges =
    editorNodes.length > 0
      ? editorEdges
      : persistedEdges.length > 0
      ? persistedEdges
      : directEdges.length > 0
      ? directEdges
      : versionEdges;

  return {
    id: typeof flow?.id === 'string' ? flow.id : null,
    nodes: selectedNodes.map(normalizeNode),
    edges: selectedEdges,
  };
}
