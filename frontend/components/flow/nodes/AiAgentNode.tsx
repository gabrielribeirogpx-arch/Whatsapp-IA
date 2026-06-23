'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { NodeStatus } from './CompactFlowNode';

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
  const tools = baseTools + nodeTools + subflows + webhooks;
  const behavior = nodeData.after_agent_behavior || nodeData.after_answer_behavior || 'wait_same_node';
  const behaviorLabel = behavior === 'end_flow' ? 'Encerra atendimento' : behavior === 'continue_to_next' ? 'Continua fluxo' : 'Aguardando mensagem';
  const model = nodeData.model_override || 'Modelo global';
  const isActive = nodeData.use_memory !== false;
  const entered = typeof (nodeData.analytics as { entered?: unknown } | null)?.entered === 'number' ? (nodeData.analytics as { entered: number }).entered : 0;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="IA Agente"
      emoji="🤖"
      badge="AGENTE"
      badgeTitle="Usa IA para decidir e executar ferramentas permitidas"
      badgeTone={{ background: '#f4f0ff', color: '#6d28d9' }}
      accent="linear-gradient(135deg, #7c3aed, #4f46e5 52%, #06b6d4)"
      summary="Orquestra ações inteligentes usando IA, memória e ferramentas do fluxo."
      meta={isActive ? 'Ativo' : 'Inativo'}
      metrics={[
        { label: 'Modelo de IA', value: model, icon: '✦', tone: '#4f46e5' },
        { label: 'Ações', value: tools, icon: '⚡', tone: '#7c3aed' },
        { label: 'Entradas', value: entered, icon: '↪', tone: '#2563eb' },
        { label: 'Saídas', value: Math.max(0, nodeTools + subflows + webhooks), icon: '↗', tone: '#16a34a' },
      ]}
      chips={[nodeData.use_memory === false ? 'Memória OFF' : 'Memória ON', `${baseTools} ferramentas`, behaviorLabel]}
      footer={<NodeStatus active={isActive} label={behaviorLabel} />}
      premium
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics as any}
    />
  );
}
