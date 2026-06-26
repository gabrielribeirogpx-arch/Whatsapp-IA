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
  const tools = Array.isArray(nodeData.tools) ? nodeData.tools : [];
  const integrations = Array.isArray(nodeData.integrations) ? nodeData.integrations : [];
  const statuses = Array.isArray(nodeData.statuses) && nodeData.statuses.length > 0
    ? nodeData.statuses
    : ['Saudação', 'Agenda', 'Consulta', 'Cancelamento'];
  const systemType = nodeData.system_type || 'custom';
  const badge = SYSTEM_BADGES[systemType] || nodeData.name || 'Sistema IA';

  return (
    <div className={`ai-system-node${selected ? ' is-selected' : ''}${nodeData.running ? ' is-running' : ''}${nodeData.hasValidationError ? ' has-error' : ''}`}>
      <Handle type="target" position={Position.Left} id="default" />
      <div className="ai-system-node-header">
        <span className="ai-system-node-kicker">🤖 Sistema IA</span>
        <span className="ai-system-node-badge">{badge}</span>
      </div>
      <h3>{nodeData.name || nodeData.label || badge}</h3>
      <div className="ai-system-node-summary">
        <span>Dispatcher</span>
        <span>Greeting</span>
        <span>Calendar</span>
        <span>Fallback</span>
      </div>
      <div className="ai-system-node-tools">
        {(tools.length ? tools : ['Google Calendar', 'Google Drive']).slice(0, 4).map((tool) => <em key={tool}>{tool}</em>)}
      </div>
      <div className="ai-system-node-statuses">
        {statuses.slice(0, 4).map((status) => <small key={status}>🟢 {status}</small>)}
      </div>
      <div className="ai-system-node-footer">
        <span>{internalNodes.length || 4} agentes</span>
        <span>{integrations.length || 1} integração</span>
        <span>{tools.length || 5} ferramentas</span>
        <span>{nodeData.average_time || 'Tempo médio'}</span>
      </div>
      <button type="button" className="ai-system-node-toggle" onClick={(event) => { event.stopPropagation(); nodeData.onToggleSystem?.(id); }}>
        {nodeData.collapsed === false ? '▲ Recolher' : '▼ Expandir'}
      </button>
      <Handle type="source" position={Position.Right} id="default" />
    </div>
  );
}

export default memo(AiSystemNode);
