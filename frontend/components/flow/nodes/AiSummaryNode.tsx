'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type AiSummaryNodeData = {
  summary_source?: string;
  summary_format?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  analytics?: unknown;
};

const FORMAT_LABELS: Record<string, string> = {
  short: 'curto',
  detailed: 'detalhado',
  bullet_points: 'tópicos',
  handoff: 'handoff',
};

export default function AiSummaryNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiSummaryNodeData;
  const source = nodeData.summary_source === 'custom_text' ? 'texto customizado' : 'histórico';
  const format = FORMAT_LABELS[nodeData.summary_format || 'handoff'] || 'handoff';
  return <CompactFlowNode id={id} selected={selected} running={nodeData.running} title="IA Resumo" emoji="📝" badge="IA" badgeTone={{ background: '#f5f3ff', color: '#6d28d9' }} accent="linear-gradient(90deg, #7c3aed, #06b6d4)" summary={truncateText(`Resumo ${format} usando ${source}`, 72, 'Resume conversa ou texto para handoff/CRM.')} isStart={nodeData.isStart} hasValidationError={nodeData.hasValidationError} onToggleStart={nodeData.onToggleStart} analytics={nodeData.analytics} />;
}
