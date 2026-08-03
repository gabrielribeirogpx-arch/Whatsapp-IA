'use client';

import { memo } from 'react';
import type { NodeProps } from 'reactflow';
import CompactFlowNode, { NodeStatus, truncateText } from './CompactFlowNode';
import MCPMark from '../MCPMark';

function MCPToolNode({ id, data, selected, isConnectable }: NodeProps) {
  const configured = Boolean(data?.connection_id && data?.tool_name && data?.output_variable);
  const state = String(data?.runtime_state || (configured ? 'configured' : 'unconfigured'));
  const labels: Record<string, string> = { unconfigured: 'Configuração pendente', configured: 'Configurado', running: 'Executando', success: 'Configurado', error: 'Erro', timeout: 'Atenção' };
  const classification = String(data?.tool_classification || 'READ').toUpperCase();
  const risk = classification === 'DESTRUCTIVE' || classification === 'DELETE' ? 'DELETE' : classification === 'WRITE' ? 'WRITE' : 'READ';
  const body = configured ? (
    <div className="mcp-node-details">
      <div className="mcp-node-detail"><span aria-hidden="true">📡</span><span><small>Servidor</small><strong>{truncateText(data?.server_name, 26)}</strong></span></div>
      <div className="mcp-node-detail"><span aria-hidden="true">🛠</span><span><small>Ferramenta</small><strong>{truncateText(data?.tool_name, 30)}</strong></span></div>
      <div className="mcp-node-detail"><span aria-hidden="true">💾</span><span><small>Variável de saída</small><strong>{truncateText(data?.output_variable, 26)}</strong></span></div>
      <span className={`mcp-node-risk is-${risk.toLowerCase()}`}>{risk}</span>
    </div>
  ) : <div className="mcp-node-empty"><span aria-hidden="true">⚠</span><strong>Configure uma conexão MCP</strong></div>;

  return <CompactFlowNode className="mcp-tool-node" id={id} selected={selected} running={state === 'running'} isConnectable={isConnectable} title="MCP Tool" emoji={<MCPMark className="mcp-mark" />} badge="MCP" badgeTone={{ background: '#f5f3ff', color: '#6d5bd0' }} accent="#7667df" summary="" bodyContent={body} statusLabel={labels[state] || labels.configured} statusActive={configured && state !== 'error' && state !== 'timeout'} sourceHandles={[{ id: 'success', label: 'Success', color: '#16a34a' }, { id: 'error', label: 'Error', color: '#dc2626' }, { id: 'timeout', label: 'Timeout', color: '#eab308' }]} footer={<NodeStatus active={configured} label={labels[state] || labels.configured} />} />;
}

export default memo(MCPToolNode);
