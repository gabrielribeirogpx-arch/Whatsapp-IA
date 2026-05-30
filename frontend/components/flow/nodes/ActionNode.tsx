'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type ActionNodeData = {
  label?: string;
  action?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function ActionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ActionNodeData;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Ação"
      emoji="⚡"
      badge="LOGIC"
      badgeTone={{ background: '#f5f3ff', color: '#5b21b6' }}
      accent="linear-gradient(90deg, #7c3aed, #8b5cf6)"
      summary={truncateText(nodeData.action || nodeData.label, 50, 'Ação não configurada')}
      meta="Automação interna"
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}
