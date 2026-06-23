'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

const ACTION_TYPE_LABELS: Record<string, string> = {
  create_lead: 'Criar Lead',
  add_tag: 'Adicionar Tag',
  notify_team: 'Notificar Equipe',
  create_task: 'Criar tarefa',
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
  task_title?: string;
  task_description?: string;
  task_priority?: string;
  task_assignee?: string;
  task_due_minutes?: string | number;
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
  const taskTitle = String(nodeData.task_title || nodeData.params?.task_title || '').trim();
  const taskPriority = String(nodeData.task_priority || nodeData.params?.task_priority || 'normal').toLowerCase();
  const taskPriorityLabel = NOTIFICATION_PRIORITY_LABELS[taskPriority] || 'Normal';
  const taskAssignee = String(nodeData.task_assignee || nodeData.params?.task_assignee || '').trim();
  const taskDueMinutes = String(nodeData.task_due_minutes || nodeData.params?.task_due_minutes || '').trim();
  const actionLabel = actionType === 'set_conversation_mode' && modeLabel
    ? `Alterar modo → ${modeLabel}`
    : ACTION_TYPE_LABELS[actionType] || nodeData.label;
  const notifySummary = [actionLabel, notificationTitle, notificationMessage].filter(Boolean).join(' • ');
  const taskSummary = ['📝 Criar tarefa', taskTitle || 'Título não definido', `Prioridade: ${taskPriorityLabel}`, taskAssignee ? `Responsável: ${taskAssignee}` : 'Responsável: -', taskDueMinutes ? `Prazo: ${taskDueMinutes} min` : 'Prazo: 60 min'].join(' • ');

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Ação"
      emoji="⚡"
      badge="LOGIC"
      badgeTone={{ background: '#ccfbf1', color: '#0f766e' }}
      accent="linear-gradient(135deg, #14b8a6, #2563eb)"
      summary={truncateText(actionType === 'notify_team' ? notifySummary : actionType === 'create_task' ? taskSummary : actionLabel, 100, 'Ação não configurada')}
      meta={actionType === 'notify_team' ? `Prioridade: ${notificationPriorityLabel}` : actionType === 'create_task' ? `Prioridade: ${taskPriorityLabel}` : 'Automação interna'}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
      statusLabel="Automação pronta"
    />
  );
}
