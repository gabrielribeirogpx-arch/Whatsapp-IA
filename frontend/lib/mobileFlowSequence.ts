import type { Edge, Node } from 'reactflow';

export type MobileFlowSequenceItem = {
  node: Node;
  depth: number;
  incomingLabel?: string;
  isCycle?: boolean;
};

export type MobileFlowSequence = {
  connected: MobileFlowSequenceItem[];
  disconnected: Node[];
};

/**
 * Produces a stable, readable traversal without changing canvas coordinates.
 * Starts at explicitly marked start nodes (then roots), preserves every branch,
 * and records cycles instead of recursively following them forever.
 */
export function buildMobileFlowSequence(nodes: Node[], edges: Edge[]): MobileFlowSequence {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const outgoing = new Map<string, Edge[]>();
  const incoming = new Set<string>();
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    const current = outgoing.get(edge.source) || [];
    current.push(edge);
    outgoing.set(edge.source, current);
    incoming.add(edge.target);
  }
  const roots = nodes.filter((node) => (node.data as { isStart?: boolean })?.isStart);
  const starts = roots.length ? roots : nodes.filter((node) => !incoming.has(node.id));
  const visited = new Set<string>();
  const connected: MobileFlowSequenceItem[] = [];
  const walk = (id: string, depth: number, incomingLabel?: string, path = new Set<string>()) => {
    const node = byId.get(id);
    if (!node) return;
    if (path.has(id)) {
      connected.push({ node, depth, incomingLabel, isCycle: true });
      return;
    }
    if (visited.has(id)) return;
    visited.add(id);
    connected.push({ node, depth, incomingLabel });
    const nextPath = new Set(path);
    nextPath.add(id);
    (outgoing.get(id) || []).forEach((edge) => {
      const label = String(edge.label || edge.sourceHandle || (edge.data as { sourceHandle?: string } | undefined)?.sourceHandle || '').trim() || undefined;
      walk(edge.target, depth + 1, label, nextPath);
    });
  };
  starts.forEach((node) => walk(node.id, 0));
  return { connected, disconnected: nodes.filter((node) => !visited.has(node.id)) };
}
