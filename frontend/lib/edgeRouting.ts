export type EdgeRoutingMode = 'simple' | 'orthogonal' | 'loop_external';
export type EdgeRoutingPreference = 'automatic' | 'curved' | 'orthogonal';

export type Point = { x: number; y: number };
export type NodeBox = { id: string; x: number; y: number; width: number; height: number };
export type RoutingEdge = { id?: string; source: string; target: string; data?: Record<string, unknown> | null };
export type RoutingDecision = {
  mode: EdgeRoutingMode;
  reason: 'forced_curved' | 'forced_orthogonal' | 'self_loop' | 'return_connection' | 'graph_cycle' | 'loop_marker' | 'node_intersection' | 'edge_crossings' | 'clear_corridor';
  intersectionsCount: number;
  estimatedCrossings: number;
  isLoop: boolean;
  pathCost: number;
};

const DEFAULT_WIDTH = 260;
const DEFAULT_HEIGHT = 140;

export const nodeBoundingBox = (node: Partial<NodeBox> & { id: string }): NodeBox => ({
  id: node.id,
  x: Number(node.x || 0),
  y: Number(node.y || 0),
  width: Math.max(1, Number(node.width || DEFAULT_WIDTH)),
  height: Math.max(1, Number(node.height || DEFAULT_HEIGHT)),
});

export const boxCenter = (box: NodeBox): Point => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });

function orientation(a: Point, b: Point, c: Point) {
  return Math.sign((b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y));
}

function segmentsCross(a: Point, b: Point, c: Point, d: Point) {
  return orientation(a, b, c) !== orientation(a, b, d) && orientation(c, d, a) !== orientation(c, d, b);
}

/** Liang–Barsky segment/rectangle test, expanded by the requested safety margin. */
export function segmentIntersectsBox(start: Point, end: Point, box: NodeBox, margin = 16): boolean {
  const left = box.x - margin; const right = box.x + box.width + margin;
  const top = box.y - margin; const bottom = box.y + box.height + margin;
  const dx = end.x - start.x; const dy = end.y - start.y;
  const p = [-dx, dx, -dy, dy];
  const q = [start.x - left, right - start.x, start.y - top, bottom - start.y];
  let low = 0; let high = 1;
  for (let index = 0; index < 4; index += 1) {
    if (p[index] === 0 && q[index] < 0) return false;
    if (p[index] === 0) continue;
    const ratio = q[index] / p[index];
    if (p[index] < 0) low = Math.max(low, ratio); else high = Math.min(high, ratio);
    if (low > high) return false;
  }
  return true;
}

/** Returns only third-party cards hit by a candidate path. Endpoints are deliberately ignored. */
export function routeIntersectsNodes(path: Point[], nodes: NodeBox[], margin = 16, excludedNodeIds = new Set<string>()): NodeBox[] {
  return nodes.filter((node) => !excludedNodeIds.has(node.id) && path.some((point, index) => index > 0 && segmentIntersectsBox(path[index - 1], point, node, margin)));
}

function estimatedEdgeCrossings(start: Point, end: Point, edge: RoutingEdge, nodes: NodeBox[], allEdges: RoutingEdge[]) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return allEdges.filter((candidate) => {
    if (candidate.id && candidate.id === edge.id) return false;
    if ([candidate.source, candidate.target].some((id) => id === edge.source || id === edge.target)) return false;
    const source = byId.get(candidate.source); const target = byId.get(candidate.target);
    return Boolean(source && target && segmentsCross(start, end, boxCenter(source), boxCenter(target)));
  }).length;
}

function closesGraphCycle(edge: RoutingEdge, allEdges: RoutingEdge[]) {
  const outgoing = new Map<string, string[]>();
  allEdges.forEach((candidate) => {
    if (candidate.id && candidate.id === edge.id) return;
    outgoing.set(candidate.source, [...(outgoing.get(candidate.source) || []), candidate.target]);
  });
  const pending = [edge.target]; const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === edge.source) return true;
    if (visited.has(current)) continue;
    visited.add(current); pending.push(...(outgoing.get(current) || []));
  }
  return false;
}

export function selectEdgeRoutingMode({ sourceNode, targetNode, allNodes, edge, allEdges = [], preference = 'automatic', margin = 16 }: {
  sourceNode: NodeBox; targetNode: NodeBox; allNodes: NodeBox[]; edge: RoutingEdge; allEdges?: RoutingEdge[]; preference?: EdgeRoutingPreference; margin?: number;
}): RoutingDecision {
  const source = nodeBoundingBox(sourceNode); const target = nodeBoundingBox(targetNode);
  const start = boxCenter(source); const end = boxCenter(target);
  const distance = Math.hypot(end.x - start.x, end.y - start.y);
  const markerLoop = edge.data?.is_loop === true || edge.data?.isLoop === true || edge.data?.retry === true;
  const selfLoop = edge.source === edge.target;
  const isReturn = target.x <= source.x;
  const graphCycle = closesGraphCycle(edge, allEdges);
  const intersections = routeIntersectsNodes([start, end], allNodes.map(nodeBoundingBox), margin, new Set([source.id, target.id]));
  const crossings = estimatedEdgeCrossings(start, end, edge, allNodes, allEdges);
  const base = { intersectionsCount: intersections.length, estimatedCrossings: crossings, pathCost: Math.round(distance) };

  if (preference === 'curved') return { mode: 'simple', reason: 'forced_curved', isLoop: selfLoop || isReturn || markerLoop || graphCycle, ...base };
  if (selfLoop) return { mode: 'loop_external', reason: 'self_loop', isLoop: true, ...base };
  if (markerLoop) return { mode: 'loop_external', reason: 'loop_marker', isLoop: true, ...base };
  if (graphCycle) return { mode: 'loop_external', reason: 'graph_cycle', isLoop: true, ...base };
  if (isReturn) return { mode: 'loop_external', reason: 'return_connection', isLoop: true, ...base };
  if (preference === 'orthogonal') return { mode: 'orthogonal', reason: 'forced_orthogonal', isLoop: false, ...base };
  if (intersections.length) return { mode: 'orthogonal', reason: 'node_intersection', isLoop: false, ...base };
  if (crossings > 1) return { mode: 'orthogonal', reason: 'edge_crossings', isLoop: false, ...base };
  return { mode: 'simple', reason: 'clear_corridor', isLoop: false, ...base };
}

export function orthogonalWaypoints(start: Point, end: Point, nodes: NodeBox[], excluded: Set<string>, margin = 24): Point[] {
  const middleX = (start.x + end.x) / 2;
  const direct = [start, { x: middleX, y: start.y }, { x: middleX, y: end.y }, end];
  const obstacles = routeIntersectsNodes(direct, nodes, margin, excluded);
  if (!obstacles.length) return direct;
  const above = Math.min(start.y, end.y, ...obstacles.map((node) => node.y)) - margin;
  const below = Math.max(start.y, end.y, ...obstacles.map((node) => node.y + node.height)) + margin;
  const upper = [start, { x: start.x + margin, y: start.y }, { x: start.x + margin, y: above }, { x: end.x - margin, y: above }, { x: end.x - margin, y: end.y }, end];
  const lower = [start, { x: start.x + margin, y: start.y }, { x: start.x + margin, y: below }, { x: end.x - margin, y: below }, { x: end.x - margin, y: end.y }, end];
  const length = (path: Point[]) => path.slice(1).reduce((sum, point, index) => sum + Math.abs(point.x - path[index].x) + Math.abs(point.y - path[index].y), 0);
  const score = (path: Point[]) => (routeIntersectsNodes(path, nodes, margin, excluded).length * 1_000_000) + length(path);
  const graphTop = Math.min(...nodes.filter((node) => !excluded.has(node.id)).map((node) => node.y), start.y, end.y) - margin * 2;
  const graphBottom = Math.max(...nodes.filter((node) => !excluded.has(node.id)).map((node) => node.y + node.height), start.y, end.y) + margin * 2;
  const outerUpper = [start, { x: start.x + margin, y: start.y }, { x: start.x + margin, y: graphTop }, { x: end.x - margin, y: graphTop }, { x: end.x - margin, y: end.y }, end];
  const outerLower = [start, { x: start.x + margin, y: start.y }, { x: start.x + margin, y: graphBottom }, { x: end.x - margin, y: graphBottom }, { x: end.x - margin, y: end.y }, end];
  return [upper, lower, outerUpper, outerLower].sort((left, right) => score(left) - score(right))[0];
}

export const pointsToPath = (points: Point[]) => points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
