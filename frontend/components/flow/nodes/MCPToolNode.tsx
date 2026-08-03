'use client';

import { memo } from 'react';
import type { NodeProps } from 'reactflow';
import CompactFlowNode, { NodeStatus, truncateText } from './CompactFlowNode';
import MCPMark from '../MCPMark';

function MCPToolNode({ id, data, selected, isConnectable }: NodeProps) {
  const configured = Boolean(data?.connection_id && data?.tool_name && data?.output_variable);
  const state = String(data?.runtime_state || (configured ? 'configured' : 'unconfigured'));
  const labels: Record<string, string> = { unconfigured: 'Configure uma conexão MCP', configured: 'Configurado', running: 'Executando', success: 'Configurado', error: 'Erro', timeout: 'Atenção' };
  const classification = String(data?.tool_classification || 'READ').toUpperCase();
  const classLabel = classification === 'DESTRUCTIVE' || classification === 'DELETE' ? '🔴 DELETE' : classification === 'WRITE' ? '🟠 WRITE' : '🟢 READ';
  const summary = configured
    ? `📡 ${truncateText(data?.server_name, 26)}\n🛠 ${truncateText(data?.tool_name, 30)}\n💾 ${truncateText(data?.output_variable, 26)}`
    : '⚠ Configure uma conexão MCP';
  return <CompactFlowNode id={id} selected={selected} running={state === 'running'} isConnectable={isConnectable} title="MCP Tool" emoji={<MCPMark className="mcp-mark" />} badge="MCP" badgeTone={{ background: '#eef2ff', color: '#4f46e5' }} accent="#6366f1" summary={summary} chips={configured ? [classLabel] : []} statusLabel={labels[state] || labels.configured} statusActive={configured && state !== 'error' && state !== 'timeout'} sourceHandles={[{ id: 'success', label: '✓ Success', color: '#16a34a' }, { id: 'error', label: '× Error', color: '#dc2626' }, { id: 'timeout', label: '◷ Timeout', color: '#eab308' }]} footer={<NodeStatus active={configured} label={labels[state] || labels.configured} />} />;
}

export default memo(MCPToolNode);
