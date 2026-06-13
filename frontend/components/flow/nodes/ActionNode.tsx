'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

const ACTION_TYPE_LABELS: Record<string, string> = {
  create_lead: 'Criar Lead',
  add_tag: 'Adicionar Tag',
  notify_team: 'Notificar Equipe',
  transfer_human: 'Transferir para Humano',
  set_conversation_mode: 'Alterar modo da conversa',
};

const NOTIFICATION_PRIORITY_LABELS: Record<string, string> = {
  low: 'Baixa',
  normal: 'Normal',
  high: 'Alta',
};

const CONVERSATION_MODE_LABELS: Record<string, string> = {
  human: 'Humano',
  bot: 'Bot',
  ai: 'IA',
};

type ActionNodeData = {
  label?: string;
  action?: string;
  action_type?: string;
  mode?: string;
  params?: Record<string, unknown>;
  notification_title?: string;
  notification_message?: string;
  notification_priority?: string;
  message?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function ActionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ActionNodeData;
  const actionType = nodeData.action_type || nodeData.action || '';
  const mode = String(nodeData.mode || nodeData.params?.mode || '').toLowerCase();
  const modeLabel = CONVERSATION_MODE_LABELS[mode];
  const notificationTitle = String(nodeData.notification_title || nodeData.params?.notification_title || '').trim();
  const notificationMessage = String(
    nodeData.notification_message || nodeData.params?.notification_message || nodeData.message || nodeData.params?.message || ''
  ).trim();
  const notificationPriority = String(nodeData.notification_priority || nodeData.params?.notification_priority || 'normal').toLowerCase();
  const notificationPriorityLabel = NOTIFICATION_PRIORITY_LABELS[notificationPriority] || 'Normal';
  const actionLabel = actionType === 'set_conversation_mode' && modeLabel
    ? `Alterar modo → ${modeLabel}`
    : ACTION_TYPE_LABELS[actionType] || nodeData.label;
  const notifySummary = [actionLabel, notificationTitle, notificationMessage].filter(Boolean).join(' • ');

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
      summary={truncateText(actionType === 'notify_team' ? notifySummary : actionLabel, 80, 'Ação não configurada')}
      meta={actionType === 'notify_team' ? `Prioridade: ${notificationPriorityLabel}` : 'Automação interna'}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}
