'use client';

import { memo } from 'react';
import type { NodeProps } from 'reactflow';
import CompactFlowNode, { NodeStatus, truncateText } from './CompactFlowNode';
import MCPMark from '../MCPMark';
import { getNodeHandleContract } from '@/lib/nodeHandleContract';

function MCPToolNode({ id, data, selected, isConnectable }: NodeProps) {
  const hasConnection = Boolean(data?.connection_id);
  const hasTool = Boolean(data?.tool_name);
  const hasOutput = Boolean(data?.output_variable);
  const inputSchema = data?.input_schema && typeof data.input_schema === 'object' ? data.input_schema as { required?: string[] } : {};
  const args = data?.arguments && typeof data.arguments === 'object' ? data.arguments as Record<string, unknown> : {};
  const requiredArgumentsAreValid = (inputSchema.required || []).every((name) => args[name] !== undefined && args[name] !== null && args[name] !== '');
  const configured = hasConnection && hasTool && hasOutput && requiredArgumentsAreValid;
  const state = String(data?.runtime_state || (configured ? 'configured' : 'unconfigured'));
  const incompleteLabel = hasConnection ? 'Configuração incompleta' : 'Não configurado';
  const labels: Record<string, string> = { unconfigured: incompleteLabel, configured: 'Configurado', running: 'Executando', success: 'Configurado', error: 'Erro', timeout: 'Atenção' };
  const statusLabel = ['running', 'error', 'timeout'].includes(state) ? labels[state] : (configured ? 'Configurado' : incompleteLabel);
  const classification = String(data?.tool_classification || 'READ').toUpperCase();
  const risk = classification === 'DESTRUCTIVE' || classification === 'DELETE' ? 'DELETE' : classification === 'WRITE' ? 'WRITE' : 'READ';
  const connectionName = data?.connection_name || data?.server_name || 'Conexão MCP';
  const body = hasConnection ? (
    <div className="mcp-node-details">
      <div className="mcp-node-detail"><span aria-hidden="true">📡</span><span><small>Conexão</small><strong>{truncateText(connectionName, 26)}</strong></span></div>
      {data?.connection_verified === true ? <div className="mcp-node-detail"><span aria-hidden="true">✓</span><span><strong>Conexão verificada</strong></span></div> : null}
      <div className="mcp-node-detail"><span aria-hidden="true">🛠</span><span><small>Ferramenta</small><strong>{hasTool ? truncateText(data?.tool_name, 30) : 'Selecione uma ferramenta'}</strong></span></div>
      {hasOutput ? <div className="mcp-node-detail"><span aria-hidden="true">💾</span><span><small>Saída</small><strong>{truncateText(data?.output_variable, 26)}</strong></span></div> : null}
      {hasTool ? <span className={`mcp-node-risk is-${risk.toLowerCase()}`}>{risk}</span> : null}
    </div>
  ) : <div className="mcp-node-empty"><span aria-hidden="true">⚠</span><strong>Configure uma conexão MCP</strong></div>;

  const contract = getNodeHandleContract({ type: 'mcp_tool', data });
  const handleColors: Record<string, string> = { success: '#16a34a', error: '#dc2626', timeout: '#eab308' };

  return <CompactFlowNode className="mcp-tool-node" id={id} selected={selected} running={state === 'running'} isConnectable={isConnectable} title="MCP Tool" emoji={<MCPMark className="mcp-mark" />} badge="MCP" badgeTone={{ background: '#f5f3ff', color: '#6d5bd0' }} accent="#7667df" summary="" bodyContent={body} statusLabel={statusLabel} statusActive={configured && state !== 'error' && state !== 'timeout'} sourceHandles={contract.sourceHandles.map((handle) => ({ id: handle, label: handle[0].toUpperCase() + handle.slice(1), color: handleColors[handle] }))} footer={<NodeStatus active={configured} label={statusLabel} />} />;
}

export default memo(MCPToolNode);
