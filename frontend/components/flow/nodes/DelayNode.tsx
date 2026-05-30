'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type DelayNodeData = {
  label?: string;
  content?: string;
  delay?: string | number;
  seconds?: string | number;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function DelayNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as DelayNodeData;
  const value = nodeData.seconds || nodeData.delay || nodeData.content || '3';

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Delay"
      emoji="⏱️"
      badge="WAIT"
      badgeTone={{ background: '#ecfeff', color: '#0e7490' }}
      accent="linear-gradient(90deg, #0891b2, #06b6d4)"
      summary={`Aguardar ${value}s`}
      meta="Pausa no fluxo"
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}
