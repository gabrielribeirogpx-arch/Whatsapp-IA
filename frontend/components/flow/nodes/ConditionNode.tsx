'use client';

import { Handle, NodeProps, Position } from '@xyflow/react';

type ConditionNodeData = {
  label?: string;
  condition?: string;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function ConditionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ConditionNodeData;

  return (
    <div
      className={selected ? 'selected' : undefined}
      style={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, padding: 12, minWidth: 240 }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Condição'}</div>
      <input
        value={nodeData.condition || ''}
        onChange={(event) => nodeData.onChange?.(id, { condition: event.target.value })}
        placeholder="Ex.: mensagem contém 'plano'"
        style={{ width: '100%', border: '1px solid #e5e7eb', borderRadius: 6, padding: '8px 10px' }}
      />
      <Handle type="source" position={Position.Right} id="true" style={{ top: '35%' }} />
      <Handle type="source" position={Position.Right} id="false" style={{ top: '70%' }} />
    </div>
  );
}
