'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiAgentNodeData = {
  allowed_tools?: string[];
  after_agent_behavior?: string;
  after_answer_behavior?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  analytics?: unknown;
};

export default function AiAgentNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiAgentNodeData;
  const tools = Array.isArray(nodeData.allowed_tools) ? nodeData.allowed_tools.length : 2;
  const behavior = nodeData.after_agent_behavior || nodeData.after_answer_behavior || 'wait_same_node';
  const summary = `${tools} ferramentas · ${behavior}`;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="IA Agente"
      emoji="🧠"
      badge="AGENTE"
      badgeTitle="Usa IA para decidir e executar ferramentas permitidas"
      badgeTone={{ background: '#f5f3ff', color: '#6d28d9' }}
      accent="linear-gradient(90deg, #8b5cf6, #06b6d4)"
      summary={truncateText(summary, 58, '2 ferramentas · wait_same_node')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
