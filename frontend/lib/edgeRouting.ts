export type EdgeRoutingMode = 'simple' | 'orthogonal' | 'feedback_local' | 'loop_external' | 'convergence_external';
export type EdgeRoutingPreference = 'automatic' | 'curved' | 'orthogonal';
export type Point = { x: number; y: number };
export type NodeBox = { id: string; x: number; y: number; width: number; height: number };
export type RoutingEdge = { id?: string; source: string; target: string; data?: Record<string, unknown> | null };
export type ExternalLane = 'top' | 'bottom' | 'left' | 'right';
export type RouteMetrics = { pathLength: number; nodeIntersections: number; nearNodeCount: number; edgeCrossings: number; bendCount: number; centerTraversals: number; labelCollisions: number; totalCost: number };
export type RouteCandidate = RouteMetrics & { lane: ExternalLane; laneIndex: number; points: Point[] };
export type RoutingDecision = {
  mode: EdgeRoutingMode;
  reason: 'forced_curved' | 'forced_orthogonal' | 'self_loop' | 'return_connection' | 'graph_cycle' | 'loop_marker' | 'node_intersection' | 'edge_crossings' | 'clear_corridor' | 'long_convergence_with_obstacles' | 'long_convergence_to_shared_target';
  intersectionsCount: number; estimatedCrossings: number; isLoop: boolean; pathCost: number;
};

export const NODE_CLEARANCE = 28;
export const EXTERNAL_LANE_GAP = 32;
export const LOCAL_FEEDBACK_GAP = 36;
const DEFAULT_WIDTH = 260;
const DEFAULT_HEIGHT = 140;

export const nodeBoundingBox = (node: Partial<NodeBox> & { id: string }): NodeBox => ({ id: node.id, x: Number(node.x || 0), y: Number(node.y || 0), width: Math.max(1, Number(node.width || DEFAULT_WIDTH)), height: Math.max(1, Number(node.height || DEFAULT_HEIGHT)) });
export const boxCenter = (box: NodeBox): Point => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
export function graphBoundingBox(nodes: NodeBox[]) {
  if (!nodes.length) return { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  return { minX: Math.min(...nodes.map(n => n.x)), minY: Math.min(...nodes.map(n => n.y)), maxX: Math.max(...nodes.map(n => n.x + n.width)), maxY: Math.max(...nodes.map(n => n.y + n.height)) };
}

function orientation(a: Point, b: Point, c: Point) { return Math.sign((b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y)); }
function segmentsCross(a: Point, b: Point, c: Point, d: Point) { return orientation(a, b, c) !== orientation(a, b, d) && orientation(c, d, a) !== orientation(c, d, b); }
export function segmentIntersectsBox(start: Point, end: Point, box: NodeBox, margin = NODE_CLEARANCE): boolean {
  const left = box.x - margin, right = box.x + box.width + margin, top = box.y - margin, bottom = box.y + box.height + margin;
  const dx = end.x - start.x, dy = end.y - start.y, p = [-dx, dx, -dy, dy], q = [start.x - left, right - start.x, start.y - top, bottom - start.y];
  let low = 0, high = 1;
  for (let i = 0; i < 4; i += 1) { if (p[i] === 0 && q[i] < 0) return false; if (p[i] === 0) continue; const ratio = q[i] / p[i]; if (p[i] < 0) low = Math.max(low, ratio); else high = Math.min(high, ratio); if (low > high) return false; }
  return true;
}
export function routeIntersectsNodes(path: Point[], nodes: NodeBox[], margin = NODE_CLEARANCE, excludedNodeIds = new Set<string>()): NodeBox[] { return nodes.filter(node => !excludedNodeIds.has(node.id) && path.some((p, i) => i > 0 && segmentIntersectsBox(path[i - 1], p, node, margin))); }
function edgeCrossings(path: Point[], edge: RoutingEdge, nodes: NodeBox[], allEdges: RoutingEdge[]) {
  const byId = new Map(nodes.map(n => [n.id, n])); let count = 0;
  for (const candidate of allEdges) { if ((candidate.id && candidate.id === edge.id) || [candidate.source, candidate.target].some(id => id === edge.source || id === edge.target)) continue; const a = byId.get(candidate.source), b = byId.get(candidate.target); if (a && b && path.slice(1).some((p, i) => segmentsCross(path[i], p, boxCenter(a), boxCenter(b)))) count += 1; }
  return count;
}
function closesGraphCycle(edge: RoutingEdge, allEdges: RoutingEdge[]) { const outgoing = new Map<string, string[]>(); allEdges.forEach(e => { if (e.id && e.id === edge.id) return; outgoing.set(e.source, [...(outgoing.get(e.source) || []), e.target]); }); const pending = [edge.target], visited = new Set<string>(); while (pending.length) { const current = pending.pop()!; if (current === edge.source) return true; if (!visited.has(current)) { visited.add(current); pending.push(...(outgoing.get(current) || [])); } } return false; }

export function selectEdgeRoutingMode({ sourceNode, targetNode, allNodes, edge, allEdges = [], graphDirection = 'LR', preference = 'automatic', margin = NODE_CLEARANCE }: { sourceNode: NodeBox; targetNode: NodeBox; allNodes: NodeBox[]; edge: RoutingEdge; allEdges?: RoutingEdge[]; graphDirection?: string; preference?: EdgeRoutingPreference; margin?: number }): RoutingDecision {
  const source = nodeBoundingBox(sourceNode), target = nodeBoundingBox(targetNode), start = boxCenter(source), end = boxCenter(target);
  const distance = Math.hypot(end.x - start.x, end.y - start.y), markerLoop = edge.data?.is_loop === true || edge.data?.isLoop === true || edge.data?.retry === true, selfLoop = edge.source === edge.target, graphCycle = closesGraphCycle(edge, allEdges);
  const intersections = routeIntersectsNodes([start, end], allNodes.map(nodeBoundingBox), margin, new Set([source.id, target.id]));
  const crossings = edgeCrossings([start, end], edge, allNodes, allEdges), incoming = allEdges.filter(e => e.target === edge.target && (!e.id || e.id !== edge.id) && e.source !== edge.source).length;
  const backward = graphDirection === 'TB' ? target.y < source.y : target.x < source.x, distinctBranch = graphDirection === 'TB' ? Math.abs(end.x - start.x) > 300 : Math.abs(end.y - start.y) > 220;
  const long = distance >= 600, convergenceSignals = Number(backward) + Number(distinctBranch) + Number(intersections.length > 0) + Number(incoming > 0) + Number(crossings > 0);
  const base = { intersectionsCount: intersections.length, estimatedCrossings: crossings, pathCost: Math.round(distance) };
  if (preference === 'curved') return { mode: 'simple', reason: 'forced_curved', isLoop: selfLoop || markerLoop || graphCycle, ...base };
  if (selfLoop) return { mode: 'loop_external', reason: 'self_loop', isLoop: true, ...base };
  if (markerLoop) return { mode: 'loop_external', reason: 'loop_marker', isLoop: true, ...base };
  // A backwards connection is the common visual representation of a graph cycle.
  // Keep it local before considering the generic cycle fallback: the old ordering
  // sent even adjacent feedback edges to the bounding box of the whole graph.
  if (backward && !long) return { mode: 'feedback_local', reason: 'return_connection', isLoop: true, ...base };
  if (graphCycle) return { mode: 'loop_external', reason: 'graph_cycle', isLoop: true, ...base };
  if (preference === 'orthogonal') return { mode: 'orthogonal', reason: 'forced_orthogonal', isLoop: false, ...base };
  if (long && convergenceSignals >= 2) return { mode: 'convergence_external', reason: intersections.length || crossings ? 'long_convergence_with_obstacles' : 'long_convergence_to_shared_target', isLoop: false, ...base };
  if (backward) return { mode: 'loop_external', reason: 'return_connection', isLoop: true, ...base };
  if (intersections.length) return { mode: 'orthogonal', reason: 'node_intersection', isLoop: false, ...base };
  if (crossings > 1) return { mode: 'orthogonal', reason: 'edge_crossings', isLoop: false, ...base };
  return { mode: 'simple', reason: 'clear_corridor', isLoop: false, ...base };
}

const length = (path: Point[]) => path.slice(1).reduce((sum, p, i) => sum + Math.abs(p.x - path[i].x) + Math.abs(p.y - path[i].y), 0);
const compact = (points: Point[]) => points.filter((p, i) => !i || p.x !== points[i - 1].x || p.y !== points[i - 1].y).filter((p, i, a) => !i || i === a.length - 1 || !((a[i - 1].x === p.x && p.x === a[i + 1].x) || (a[i - 1].y === p.y && p.y === a[i + 1].y)));
function metrics(points: Point[], lane: ExternalLane, laneIndex: number, nodes: NodeBox[], excluded: Set<string>, edge: RoutingEdge, allEdges: RoutingEdge[]): RouteCandidate {
  const hits = routeIntersectsNodes(points, nodes, NODE_CLEARANCE, excluded).length, near = routeIntersectsNodes(points, nodes, NODE_CLEARANCE + 24, excluded).length - hits, crossings = edgeCrossings(points, edge, nodes, allEdges), bends = Math.max(0, points.length - 2), bounds = graphBoundingBox(nodes), center = { id: 'graph-center', x: bounds.minX + (bounds.maxX - bounds.minX) * .25, y: bounds.minY + (bounds.maxY - bounds.minY) * .25, width: (bounds.maxX - bounds.minX) * .5, height: (bounds.maxY - bounds.minY) * .5 }, centerTraversals = routeIntersectsNodes(points, [center], 0).length;
  const pathLength = length(points), labelCollisions = 0, totalCost = pathLength + hits * 1_000_000 + Math.max(0, near) * 20_000 + crossings * 8_000 + bends * 120 + centerTraversals * 12_000 + labelCollisions * 5_000;
  return { lane, laneIndex, points, pathLength, nodeIntersections: hits, nearNodeCount: Math.max(0, near), edgeCrossings: crossings, bendCount: bends, centerTraversals, labelCollisions, totalCost };
}
type HandleDirection = 'left' | 'right' | 'top' | 'bottom';
const handleStub = (point: Point, direction: HandleDirection, distance: number): Point => ({ x: point.x + (direction === 'right' ? distance : direction === 'left' ? -distance : 0), y: point.y + (direction === 'bottom' ? distance : direction === 'top' ? -distance : 0) });
export function externalRouteCandidates(start: Point, end: Point, nodes: NodeBox[], excluded: Set<string>, edge: RoutingEdge, allEdges: RoutingEdge[] = [], laneIndex = 0, sourceDirection: HandleDirection = 'right', targetDirection: HandleDirection = 'left'): RouteCandidate[] {
  const b = graphBoundingBox(nodes), offset = NODE_CLEARANCE * 2 + laneIndex * EXTERNAL_LANE_GAP, stub = NODE_CLEARANCE;
  const sourceStub = handleStub(start, sourceDirection, stub), targetStub = handleStub(end, targetDirection, stub);
  const raw: Record<ExternalLane, Point[]> = {
    top: [start, sourceStub, { x: sourceStub.x, y: b.minY - offset }, { x: targetStub.x, y: b.minY - offset }, targetStub, end],
    bottom: [start, sourceStub, { x: sourceStub.x, y: b.maxY + offset }, { x: targetStub.x, y: b.maxY + offset }, targetStub, end],
    left: [start, sourceStub, { x: b.minX - offset, y: sourceStub.y }, { x: b.minX - offset, y: targetStub.y }, targetStub, end],
    right: [start, sourceStub, { x: b.maxX + offset, y: sourceStub.y }, { x: b.maxX + offset, y: targetStub.y }, targetStub, end],
  };
  return (Object.keys(raw) as ExternalLane[]).map(lane => metrics(compact(raw[lane]), lane, laneIndex, nodes, excluded, edge, allEdges)).sort((a, b2) => a.totalCost - b2.totalCost);
}

/** Routes a feedback edge around only its endpoints, rather than around the graph.
 * Top and bottom corridors are scored with the existing obstacle/crossing metrics,
 * so the shortest clear local side wins. Parallel feedback edges get separate lanes.
 */
export function localFeedbackRouteCandidates(start: Point, end: Point, sourceNode: NodeBox, targetNode: NodeBox, nodes: NodeBox[], excluded: Set<string>, edge: RoutingEdge, allEdges: RoutingEdge[] = [], laneIndex = 0, sourceDirection: HandleDirection = 'right', targetDirection: HandleDirection = 'left'): RouteCandidate[] {
  const source = nodeBoundingBox(sourceNode), target = nodeBoundingBox(targetNode);
  const offset = NODE_CLEARANCE + laneIndex * LOCAL_FEEDBACK_GAP;
  const sourceStub = handleStub(start, sourceDirection, NODE_CLEARANCE);
  const targetStub = handleStub(end, targetDirection, NODE_CLEARANCE);
  const top = Math.min(source.y, target.y) - offset;
  const bottom = Math.max(source.y + source.height, target.y + target.height) + offset;
  const raw: Pick<Record<ExternalLane, Point[]>, 'top' | 'bottom'> = {
    top: [start, sourceStub, { x: sourceStub.x, y: top }, { x: targetStub.x, y: top }, targetStub, end],
    bottom: [start, sourceStub, { x: sourceStub.x, y: bottom }, { x: targetStub.x, y: bottom }, targetStub, end],
  };
  return (Object.keys(raw) as Array<'top' | 'bottom'>)
    .map(lane => metrics(compact(raw[lane]), lane, laneIndex, nodes, excluded, edge, allEdges))
    .sort((a, b) => a.totalCost - b.totalCost);
}
export function orthogonalWaypoints(start: Point, end: Point, nodes: NodeBox[], excluded: Set<string>, margin = NODE_CLEARANCE): Point[] { const mid = (start.x + end.x) / 2, direct = compact([start, { x: mid, y: start.y }, { x: mid, y: end.y }, end]); if (!routeIntersectsNodes(direct, nodes, margin, excluded).length) return direct; return externalRouteCandidates(start, end, nodes, excluded, { source: '', target: '' })[0].points; }
export function pointsToPath(points: Point[], radius = 12) { if (points.length < 2) return ''; let path = `M ${points[0].x} ${points[0].y}`; for (let i = 1; i < points.length - 1; i += 1) { const prev = points[i - 1], current = points[i], next = points[i + 1], inLen = Math.hypot(current.x - prev.x, current.y - prev.y), outLen = Math.hypot(next.x - current.x, next.y - current.y), r = Math.min(radius, inLen / 2, outLen / 2), before = { x: current.x + (prev.x - current.x) * r / inLen, y: current.y + (prev.y - current.y) * r / inLen }, after = { x: current.x + (next.x - current.x) * r / outLen, y: current.y + (next.y - current.y) * r / outLen }; path += ` L ${before.x} ${before.y} Q ${current.x} ${current.y} ${after.x} ${after.y}`; } const last = points[points.length - 1]; return `${path} L ${last.x} ${last.y}`; }
export function routeLabelPoint(points: Point[]) { let best = { length: -1, point: points[0] }; points.slice(1).forEach((p, i) => { const a = points[i], l = Math.hypot(p.x - a.x, p.y - a.y); if (l > best.length) best = { length: l, point: { x: (a.x + p.x) / 2, y: (a.y + p.y) / 2 } }; }); return best.point; }
