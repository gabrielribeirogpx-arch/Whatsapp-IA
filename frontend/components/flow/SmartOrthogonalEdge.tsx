'use client';

import { BaseEdge, EdgeLabelRenderer, EdgeProps, getBezierPath, useStore } from 'reactflow';
import { EdgeRoutingPreference, NodeBox, orthogonalWaypoints, pointsToPath, selectEdgeRoutingMode } from '@/lib/edgeRouting';

const debugEnabled = process.env.NEXT_PUBLIC_EDGE_ROUTING_DEBUG === 'true' || process.env.EDGE_ROUTING_DEBUG === 'true';

export default function SmartOrthogonalEdge(props: EdgeProps) {
  const { id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, label, labelStyle, data } = props;
  const graph = useStore((state) => ({ nodes: Array.from(state.nodeInternals.values()), edges: state.edges }));
  const nodes: NodeBox[] = graph.nodes.map((node) => ({ id: node.id, x: node.positionAbsolute?.x ?? node.position.x, y: node.positionAbsolute?.y ?? node.position.y, width: node.width || 260, height: node.height || 140 }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const sourceNode = byId.get(source) || { id: source, x: sourceX, y: sourceY, width: 1, height: 1 };
  const targetNode = byId.get(target) || { id: target, x: targetX, y: targetY, width: 1, height: 1 };
  const preference = String(data?.__routingPreference || 'automatic') as EdgeRoutingPreference;
  const decision = selectEdgeRoutingMode({ sourceNode, targetNode, allNodes: nodes, edge: { id, source, target, data }, allEdges: graph.edges, preference });
  const start = { x: sourceX, y: sourceY }; const end = { x: targetX, y: targetY };
  let path: string; let labelX = (sourceX + targetX) / 2; let labelY = (sourceY + targetY) / 2;

  if (decision.mode === 'simple') {
    [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  } else if (decision.mode === 'orthogonal') {
    path = pointsToPath(orthogonalWaypoints(start, end, nodes, new Set([source, target])));
  } else if (source === target) {
    const right = sourceNode.x + sourceNode.width + 56; const top = sourceNode.y - 48;
    path = pointsToPath([start, { x: right, y: start.y }, { x: right, y: top }, { x: targetX, y: top }, end]);
    labelX = right; labelY = top;
  } else {
    const graphLeft = Math.min(...nodes.map((node) => node.x), sourceNode.x, targetNode.x) - 72;
    path = pointsToPath([start, { x: sourceX + 28, y: sourceY }, { x: sourceX + 28, y: sourceY + 36 }, { x: graphLeft, y: sourceY + 36 }, { x: graphLeft, y: targetY - 36 }, { x: targetX - 28, y: targetY - 36 }, { x: targetX - 28, y: targetY }, end]);
    labelX = graphLeft; labelY = (sourceY + targetY) / 2;
  }

  const debug = `routing_mode=${decision.mode}\nreason=${decision.reason}\nintersections_count=${decision.intersectionsCount}\nis_loop=${decision.isLoop}\npath_cost=${decision.pathCost}`;
  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
    {label ? <EdgeLabelRenderer><div className="nodrag nopan" style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: 'all', ...labelStyle }}>{label}</div></EdgeLabelRenderer> : null}
    {debugEnabled ? <EdgeLabelRenderer><pre style={{ position: 'absolute', transform: `translate(8px, 8px) translate(${labelX}px,${labelY}px)`, padding: 4, borderRadius: 4, background: '#0f172acc', color: 'white', fontSize: 9, pointerEvents: 'none' }}>{debug}</pre></EdgeLabelRenderer> : null}
  </>;
}
