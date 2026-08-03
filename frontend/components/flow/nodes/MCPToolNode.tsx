'use client';

import { memo } from 'react';
import type { NodeProps } from 'reactflow';
import CompactFlowNode, { NodeStatus, truncateText } from './CompactFlowNode';

function MCPToolNode({ id, data, selected, isConnectable }: NodeProps) {
  const configured = Boolean(data?.connection_id && data?.tool_name && data?.output_variable);
  const state = String(data?.runtime_state || (configured ? 'configured' : 'unconfigured'));
  const labels: Record<string, string> = { unconfigured: 'Não configurado', configured: 'Configurado', running: 'Executando', success: 'Sucesso', error: 'Erro', timeout: 'Timeout' };
  const classification = String(data?.tool_classification || 'READ').toUpperCase();
  const classLabel = classification === 'DESTRUCTIVE' ? 'Ação destrutiva' : classification === 'WRITE' ? 'Escrita' : 'Leitura';
  return <CompactFlowNode id={id} selected={selected} running={state === 'running'} isConnectable={isConnectable} title="MCP Tool" emoji="🔌" badge="MCP" badgeTone={{ background: '#ede9fe', color: '#5b21b6' }} accent="#6366f1" summary={`Servidor: ${truncateText(data?.server_name, 28)} · Tool: ${truncateText(data?.tool_name, 32)} · Saída: ${truncateText(data?.output_variable, 28)}`} chips={[classLabel]} statusLabel={labels[state] || labels.configured} statusActive={configured && state !== 'error' && state !== 'timeout'} sourceHandles={[{ id: 'success', label: 'Sucesso', color: '#16a34a' }, { id: 'error', label: 'Erro', color: '#dc2626' }, { id: 'timeout', label: 'Timeout', color: '#d97706' }]} footer={<NodeStatus active={configured} label={labels[state] || labels.configured} />} />;
}

export default memo(MCPToolNode);
