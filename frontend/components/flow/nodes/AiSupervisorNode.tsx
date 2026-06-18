'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiSupervisorNodeData = {
  agent_ids?: string[];
  agents?: string[];
  fallback_agent_id?: string;
  fallbackAgentName?: string;
  mode?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  analytics?: unknown;
};

export default function AiSupervisorNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiSupervisorNodeData;
  const agentIds = Array.isArray(nodeData.agent_ids) ? nodeData.agent_ids : Array.isArray(nodeData.agents) ? nodeData.agents : [];
  const mode = nodeData.mode === 'multi' ? 'Multi futuro' : 'Single';
  const fallback = nodeData.fallbackAgentName || nodeData.fallback_agent_id || 'Não definido';
  const summary = `${agentIds.length} agentes · Fallback: ${fallback} · Modo: ${mode}`;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Supervisor IA"
      emoji="🧠"
      badge="SUPERVISOR"
      badgeTitle="Orquestra a escolha de um IA Agente especializado"
      badgeTone={{ background: '#ecfeff', color: '#0e7490' }}
      accent="linear-gradient(90deg, #06b6d4, #8b5cf6)"
      summary={truncateText(summary, 88, '0 agentes · Fallback: Não definido · Modo: Single')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
