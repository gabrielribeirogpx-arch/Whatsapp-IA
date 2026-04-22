'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ActionNodeData = {
  label?: string;
  action?: string;
  running?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function ActionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ActionNodeData;

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 220 }}>
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Ação'}</div>
      <input
        value={nodeData.action || ''}
        onChange={(event) => nodeData.onChange?.(id, { action: event.target.value })}
        placeholder="Nome da ação"
        className="flow-node-field"
        style={{ width: '100%', padding: '8px 10px' }}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
