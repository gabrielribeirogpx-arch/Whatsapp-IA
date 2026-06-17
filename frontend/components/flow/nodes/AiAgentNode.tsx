'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiAgentNodeData = {
  allowed_tools?: string[];
  node_tools?: unknown[];
  subflow_tools?: unknown[];
  use_memory?: boolean;
  model_override?: string;
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
  const baseTools = Array.isArray(nodeData.allowed_tools) ? nodeData.allowed_tools.length : 2;
  const nodeTools = Array.isArray(nodeData.node_tools) ? nodeData.node_tools.length : 0;
  const subflows = Array.isArray(nodeData.subflow_tools) ? nodeData.subflow_tools.length : 0;
  const webhooks = Array.isArray((nodeData as { webhooks?: unknown[] }).webhooks) ? (nodeData as { webhooks?: unknown[] }).webhooks?.length || 0 : 0;
  const tools = baseTools;
  const behavior = nodeData.after_agent_behavior || nodeData.after_answer_behavior || 'wait_same_node';
  const behaviorLabel = behavior === 'end_flow' ? 'Encerra atendimento' : behavior === 'continue_to_next' ? 'Continua fluxo' : 'Aguarda próxima mensagem';
  const model = nodeData.model_override || 'Modelo global';
  const summary = `${model} · 🛠 ${tools} · 🔀 ${nodeTools} · 📂 ${subflows} · 🌐 ${webhooks} · 🧠 ${nodeData.use_memory === false ? 'OFF' : 'ON'} · ⏳ ${behaviorLabel}`;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="IA Agente"
      emoji="🤖"
      badge="AGENTE"
      badgeTitle="Usa IA para decidir e executar ferramentas permitidas"
      badgeTone={{ background: '#f5f3ff', color: '#6d28d9' }}
      accent="linear-gradient(90deg, #8b5cf6, #06b6d4)"
      summary={truncateText(summary, 92, 'Modelo global · 🛠 2 · 🔀 0 · 📂 0 · 🌐 0 · 🧠 ON · ⏳ Aguarda próxima mensagem')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
