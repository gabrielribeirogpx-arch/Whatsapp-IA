'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiResponseNodeData = {
  instruction?: string;
  question?: string;
  model_override?: string;
  chat_model_override?: string;
  model?: string;
  memory_enabled?: boolean;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  analytics?: unknown;
};

export default function AiResponseNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiResponseNodeData;
  const model = nodeData.model_override || nodeData.chat_model_override || nodeData.model || 'Workspace';
  const memory = nodeData.memory_enabled === false ? 'memória desligada' : 'memória ligada';
  const summary = `${model} · ${memory}`;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="IA Resposta"
      emoji="🤖"
      badge="IA"
      badgeTitle="Resposta com LLM sem Base de Conhecimento"
      badgeTone={{ background: '#ecfeff', color: '#0e7490' }}
      accent="linear-gradient(90deg, #06b6d4, #2563eb)"
      summary={truncateText(summary, 58, 'Workspace · memória ligada')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
