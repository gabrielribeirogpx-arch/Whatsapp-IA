'use client';

import { Handle, NodeProps, Position } from '@xyflow/react';

type ActionNodeData = {
  label?: string;
  action?: string;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function ActionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ActionNodeData;

  return (
    <div
      className={selected ? 'selected' : undefined}
      style={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, padding: 12, minWidth: 220 }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Ação'}</div>
      <input
        value={nodeData.action || ''}
        onChange={(event) => nodeData.onChange?.(id, { action: event.target.value })}
        placeholder="Nome da ação"
        style={{ width: '100%', border: '1px solid #e5e7eb', borderRadius: 6, padding: '8px 10px' }}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
