'use client';

import { Handle, NodeProps, Position } from '@xyflow/react';

type MessageNodeData = {
  label?: string;
  content?: string;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function MessageNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MessageNodeData;

  return (
    <div
      className={selected ? 'selected' : undefined}
      style={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, padding: 12, minWidth: 240 }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Mensagem'}</div>
      <textarea
        value={nodeData.content || ''}
        onChange={(event) => nodeData.onChange?.(id, { content: event.target.value })}
        placeholder="Digite a mensagem..."
        style={{ width: '100%', minHeight: 80, border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, resize: 'vertical' }}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
