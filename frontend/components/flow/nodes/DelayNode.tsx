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
    <div
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 220, position: 'relative' }}
    >
      {/* Barra verde — tempo e espera */}
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #16a34a, #22c55e)' }}
      />

      <Handle type="target" position={Position.Left} />

      {/* Header */}
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#16a34a' }} />
        <span className="flow-node-title">{nodeData.label || 'Delay'}</span>
        <span
          className="flow-node-badge"
          style={{ background: '#f0fdf4', color: '#15803d' }}
        >
          ⏱
        </span>
      </div>

      {/* Corpo */}
      <div className="flow-node-body">
        <input
          className="flow-node-field nodrag"
          value={nodeData.content || ''}
          onChange={(e) => nodeData.onChange?.(id, { content: e.target.value })}
          placeholder="Segundos (ex: 3)"
          style={{ width: '100%', padding: '7px 9px' }}
        />
        <div style={{ marginTop: 6, fontSize: 10.5, color: '#a8b0a0' }}>
          segundos de espera
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{
          right: -6,
          width: 10,
          height: 10,
          background: '#fff',
          border: '2px solid #16a34a',
          borderRadius: '50%',
          cursor: 'crosshair',
          zIndex: 10,
        }}
      />
    </div>
  );
}
