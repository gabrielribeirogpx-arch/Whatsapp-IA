'use client';

import { memo } from 'react';
import { Handle, NodeProps, Position } from 'reactflow';

type AiSystemNodeData = {
  name?: string;
  label?: string;
  system_type?: string;
  collapsed?: boolean;
  internal_nodes?: unknown[];
  internal_edges?: unknown[];
  tools?: string[];
  integrations?: string[];
  statuses?: string[];
  average_time?: string;
  onToggleSystem?: (nodeId: string) => void;
  running?: boolean;
  isStart?: boolean;
  hasValidationError?: boolean;
};

const SYSTEM_BADGES: Record<string, string> = {
  ai_calendar_agent_system: 'Agenda Inteligente',
  ai_support_agent_system: 'Atendimento Inteligente',
  ai_sales_agent_system: 'Comercial Inteligente',
  ai_rag_agent_system: 'Conhecimento (RAG)',
  ai_mcp_advanced_system: 'MCP Automation',
  ai_custom_system: 'Sistema Personalizado',
  custom: 'Sistema Personalizado',
};

function AiSystemNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiSystemNodeData;
  const internalNodes = Array.isArray(nodeData.internal_nodes) ? nodeData.internal_nodes : [];
  const integrations = Array.isArray(nodeData.integrations) ? nodeData.integrations : [];
  const statusItems = ['Conversando', 'Agenda pronta', 'Integração ativa'];
  const specialists = [
    { icon: '🧠', label: 'Entendimento', tone: 'blue' },
    { icon: '💬', label: 'Conversa', tone: 'green' },
    { icon: '📅', label: 'Agenda', tone: 'orange' },
    { icon: '🛡', label: 'Segurança', tone: 'purple' },
  ];
  const systemType = nodeData.system_type || 'custom';
  const badge = SYSTEM_BADGES[systemType] || nodeData.name || 'Sistema IA';

  return (
    <div className={`ai-system-node${selected ? ' is-selected' : ''}${nodeData.running ? ' is-running' : ''}${nodeData.hasValidationError ? ' has-error' : ''}`}>
      <Handle type="target" position={Position.Left} id="default" />
      <div className="ai-system-node-header">
        <div>
          <span className="ai-system-node-kicker">🤖 AI System</span>
          <h3>{badge}</h3>
          <p>Assistente especializado em Google Calendar</p>
        </div>
        <span className="ai-system-node-badge">🟢 Ativo</span>
      </div>
      <div className="ai-system-node-summary">
        {specialists.map((item) => (
          <span key={item.label} className={`ai-system-node-mini-card tone-${item.tone}`}>
            <strong>{item.icon}</strong>
            <small>{item.label}</small>
          </span>
        ))}
      </div>
      <details className="ai-system-node-integrations">
        <summary><span>Integrações</span><strong>📅 Google Calendar</strong></summary>
        <ul>
          <li>✓ Criar eventos</li>
          <li>✓ Consultar agenda</li>
          <li>✓ Alterar eventos</li>
          <li>✓ Cancelar eventos</li>
        </ul>
      </details>
      <div className="ai-system-node-statuses" aria-label="Status">
        <strong>Status</strong>
        {statusItems.map((status) => <small key={status}>🟢 {status}</small>)}
      </div>
      <div className="ai-system-node-footer">
        <strong>Equipe IA</strong>
        <span>{internalNodes.length || 4} Especialistas</span>
        <span>{integrations.length || 1} Integração</span>
        <span>Google Calendar</span>
      </div>
      <button type="button" className="ai-system-node-toggle" onClick={(event) => { event.stopPropagation(); nodeData.onToggleSystem?.(id); }}>
        {nodeData.collapsed === false ? '▲ Recolher arquitetura' : '▼ Ver arquitetura'}
      </button>
      <Handle type="source" position={Position.Right} id="default" />
    </div>
  );
}

export default memo(AiSystemNode);
