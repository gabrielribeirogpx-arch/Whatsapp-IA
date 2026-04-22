'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type DelayNodeData = {
  label?: string;
  content?: string;
  running?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function DelayNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as DelayNodeData;

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 220 }}>
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Delay'}</div>
      <input
        value={nodeData.content || ''}
        onChange={(event) => nodeData.onChange?.(id, { content: event.target.value })}
        placeholder="Segundos (ex: 3)"
        className="flow-node-field"
        style={{ width: '100%', padding: '8px 10px' }}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
