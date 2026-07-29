'use client';

import { BaseEdge, EdgeLabelRenderer, EdgeProps, Position, getSmoothStepPath } from 'reactflow';

/** Orthogonal edge with an external lane for return connections. */
export default function SmartOrthogonalEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, label, labelStyle } = props;
  const isReturn = targetX <= sourceX || targetY < sourceY - 80;
  let path: string;
  let labelX: number;
  let labelY: number;

  if (isReturn) {
    const margin = 72;
    const outerX = Math.min(sourceX, targetX) - margin;
    const sourceExitX = sourceX + (sourcePosition === Position.Left ? -24 : 24);
    const targetEntryX = targetX + (targetPosition === Position.Right ? 24 : -24);
    path = `M ${sourceX} ${sourceY} L ${sourceExitX} ${sourceY} L ${sourceExitX} ${sourceY + 32} L ${outerX} ${sourceY + 32} L ${outerX} ${targetY - 32} L ${targetEntryX} ${targetY - 32} L ${targetEntryX} ${targetY} L ${targetX} ${targetY}`;
    labelX = outerX;
    labelY = (sourceY + targetY) / 2;
  } else {
    [path, labelX, labelY] = getSmoothStepPath({
      sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
      borderRadius: 6,
      offset: 28,
    });
  }

  return <>
    <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
    {label ? <EdgeLabelRenderer><div className="nodrag nopan" style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: 'all', ...labelStyle }}>{label}</div></EdgeLabelRenderer> : null}
  </>;
}
