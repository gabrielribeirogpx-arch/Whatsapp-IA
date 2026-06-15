'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiRagNodeData = {
  instruction?: string;
  question?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  analytics?: unknown;
};

export default function AiRagNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiRagNodeData;
  const summary = nodeData.question || nodeData.instruction || 'Pergunta: {{last_message}}';
  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="IA / RAG"
      emoji="✨"
      badge="Base de conhecimento"
      badgeTone={{ background: '#f5f3ff', color: '#6d28d9' }}
      accent="linear-gradient(90deg, #7c3aed, #06b6d4)"
      summary={truncateText(summary, 58, 'IA baseada na base de conhecimento')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
