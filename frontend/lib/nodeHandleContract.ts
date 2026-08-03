import { DATA_COLLECTION_HANDLES, normalizeDataCollectionEdges } from './dataCollectionHandles';

export type HandleContractNode = { type?: string | null; data?: Record<string, unknown> | null };
export type NodeHandleContract = { sourceHandles: string[]; targetHandles: string[] };

const LEGACY_HANDLE_ALIASES: Record<string, string> = { sucesso: 'success', erro: 'error', tempo_esgotado: 'timeout' };
const typeOf = (node: HandleContractNode) => String(node.type || node.data?.type || 'message').trim().toLowerCase();
const optionHandle = (value: unknown, fallback: string) => String(value ?? '').trim().toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

/** Sole editor handle contract, shared by rendering, validation, diagnostics and persistence. */
export function getNodeHandleContract(node: HandleContractNode): NodeHandleContract {
  const type = typeOf(node);
  const data = (node.data || {}) as Record<string, any>;
  let sourceHandles: string[] = ['default'];
  if (type === 'mcp_tool') sourceHandles = ['success', 'error', 'timeout'];
  else if (type === 'choice_dynamic' || (type === 'choice' && data.options_mode === 'dynamic')) sourceHandles = ['selected'];
  else if (type === 'data_collection') sourceHandles = [...DATA_COLLECTION_HANDLES];
  else if (type === 'condition') sourceHandles = ['true', 'false'];
  else if (type === 'choice') {
    const options = Array.isArray(data.buttons) ? data.buttons : Array.isArray(data.options) ? data.options : [];
    sourceHandles = options.map((choice: Record<string, unknown>, index: number) => optionHandle(choice.handleId || choice.handle_id || choice.value || choice.id || choice.label, `option_${index + 1}`));
  } else if (type === 'action' && Array.isArray(data.source_handles) && data.source_handles.length) sourceHandles = data.source_handles.map(String);
  return { sourceHandles, targetHandles: ['default'] };
}

export const normalizeLegacyHandle = (value: unknown) => {
  const normalized = String(value ?? '').trim().toLowerCase();
  return LEGACY_HANDLE_ALIASES[normalized] || normalized;
};

/** Loading/import migration only. Multi-branch handles are never coerced to default. */
export function migrateEdgeHandles<T extends { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null; data?: Record<string, unknown> | null }>(nodes: Array<HandleContractNode & { id?: string }>, edges: T[]): T[] {
  return (normalizeDataCollectionEdges(nodes as any[], edges as any[]) as T[]).map((edge) => {
    const rawSource = edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle;
    const rawTarget = edge.targetHandle ?? edge.data?.targetHandle ?? edge.data?.target_handle;
    const sourceHandle = rawSource == null || rawSource === '' ? rawSource : normalizeLegacyHandle(rawSource);
    const targetHandle = rawTarget == null || rawTarget === '' ? rawTarget : normalizeLegacyHandle(rawTarget);
    const sourceChanged = rawSource != null && sourceHandle !== rawSource;
    const targetChanged = rawTarget != null && targetHandle !== rawTarget;
    return sourceChanged || targetChanged ? { ...edge, ...(sourceChanged ? { sourceHandle } : {}), ...(targetChanged ? { targetHandle } : {}) } : edge;
  });
}
