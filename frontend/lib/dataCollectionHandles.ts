import type { Edge, Node } from 'reactflow';

export const DATA_COLLECTION_HANDLES = ['success', 'invalid', 'cancel', 'timeout'] as const;
export type DataCollectionHandle = typeof DATA_COLLECTION_HANDLES[number];

const LEGACY_ALIASES: Record<string, DataCollectionHandle> = { retry_exhausted: 'invalid' };

export const normalizeDataCollectionHandle = (value: unknown): string => {
  const handle = String(value ?? '').trim().toLowerCase();
  return LEGACY_ALIASES[handle] || handle;
};

/** Migrate explicit legacy IDs only; never guess/reconnect an absent handle. */
export const normalizeDataCollectionEdges = <T extends Edge>(nodes: Node[], edges: T[]): T[] => {
  const collectionIds = new Set(nodes.filter((node) => node.type === 'data_collection').map((node) => node.id));
  return edges.map((edge) => {
    if (!collectionIds.has(edge.source)) return edge;
    const raw = edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle;
    const sourceHandle = normalizeDataCollectionHandle(raw);
    if (!sourceHandle) return edge;
    return { ...edge, sourceHandle, data: { ...(edge.data || {}), sourceHandle } };
  });
};
