'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type Field = { name?: string; type?: string; description?: string };
type AiExtractionNodeData = { fields?: Field[]; running?: boolean; isStart?: boolean; onToggleStart?: (nodeId: string) => void; hasValidationError?: boolean; analytics?: unknown };

export default function AiExtractionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiExtractionNodeData;
  const summary = (nodeData.fields || []).map((field) => field.name).filter(Boolean).slice(0, 4).join(', ') || 'nome, email, telefone...';
  return <CompactFlowNode id={id} selected={selected} running={nodeData.running} title="IA Extração" emoji="🧾" badge="IA" badgeTone={{ background: '#ecfeff', color: '#0e7490' }} accent="linear-gradient(90deg, #0891b2, #22c55e)" summary={truncateText(`Extração: ${summary}`, 72, 'Extraia dados estruturados da conversa.')} isStart={nodeData.isStart} hasValidationError={nodeData.hasValidationError} onToggleStart={nodeData.onToggleStart} analytics={nodeData.analytics} statusLabel={`${(nodeData.fields || []).length || 3} campos`} />;
}
