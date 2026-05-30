'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type MessageNodeData = {
  label?: string;
  content?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function MessageNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MessageNodeData;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Mensagem"
      emoji="💬"
      badge="MSG"
      badgeTone={{ background: '#eef2ff', color: '#4338ca' }}
      accent="linear-gradient(90deg, #4f46e5, #6366f1)"
      summary={`"${truncateText(nodeData.content || nodeData.label, 50, 'Mensagem vazia')}"`}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}
