'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiClassificationNodeData = { categories?: string[]; running?: boolean; isStart?: boolean; onToggleStart?: (nodeId: string) => void; hasValidationError?: boolean; analytics?: unknown };

export default function AiClassificationNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiClassificationNodeData;
  const summary = (nodeData.categories || []).filter(Boolean).slice(0, 4).join(', ') || 'financeiro, vendas, suporte...';
  return <CompactFlowNode id={id} selected={selected} running={nodeData.running} title="IA Classificação" emoji="🧠" badge="IA" badgeTone={{ background: '#eef2ff', color: '#4338ca' }} accent="linear-gradient(90deg, #4f46e5, #06b6d4)" summary={truncateText(`Classificação: ${summary}`, 72, 'Classifique intenção, setor ou tipo de solicitação.')} isStart={nodeData.isStart} hasValidationError={nodeData.hasValidationError} onToggleStart={nodeData.onToggleStart} analytics={nodeData.analytics} statusLabel={`${(nodeData.categories || []).length || 4} categorias`} />;
}
