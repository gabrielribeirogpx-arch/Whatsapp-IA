'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type MessageNodeData = {
  label?: string;
  content?: string;
  running?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function MessageNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MessageNodeData;

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 240 }}>
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Mensagem'}</div>
      <textarea
        value={nodeData.content || ''}
        onChange={(event) => nodeData.onChange?.(id, { content: event.target.value })}
        placeholder="Digite a mensagem..."
        className="flow-node-field"
        style={{ width: '100%', minHeight: 80, resize: 'vertical' }}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
