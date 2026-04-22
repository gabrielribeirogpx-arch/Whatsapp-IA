'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ConditionNodeData = {
  label?: string;
  condition?: string;
  running?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function ConditionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ConditionNodeData;

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 240 }}>
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Condição'}</div>
      <input
        value={nodeData.condition || ''}
        onChange={(event) => nodeData.onChange?.(id, { condition: event.target.value })}
        placeholder="Ex.: mensagem contém 'plano'"
        className="flow-node-field"
        style={{ width: '100%', padding: '8px 10px' }}
      />
      <Handle type="source" position={Position.Right} id="true" style={{ top: '35%' }} />
      <Handle type="source" position={Position.Right} id="false" style={{ top: '70%' }} />
    </div>
  );
}
