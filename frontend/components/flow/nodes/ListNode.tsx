'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type ListRow = { id?: string; title?: string; handleId?: string };
type ListSection = { title?: string; rows?: ListRow[] };
type ListNodeData = {
  label?: string;
  body_text?: string;
  sections?: ListSection[];
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ListNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ListNodeData;
  const rows = (nodeData.sections || [])
    .flatMap((section) => section.rows || [])
    .map((row, index) => {
      const title = row.title || `Item ${index + 1}`;
      return { ...row, title, handleId: row.handleId || toHandleId(title, `option_${index + 1}`) };
    });

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Lista"
      emoji="📋"
      badge="META LIST"
      badgeTone={{ background: '#ccfbf1', color: '#0f766e' }}
      accent="linear-gradient(90deg, #0f766e, #14b8a6)"
      summary={`${rows.length} itens configurados`}
      meta="WhatsApp Interactive List"
      chips={rows.map((row) => row.title || '')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      sourceHandles={rows.map((row) => ({ id: row.handleId, label: row.title, color: '#0f766e' }))}
    />
  );
}
