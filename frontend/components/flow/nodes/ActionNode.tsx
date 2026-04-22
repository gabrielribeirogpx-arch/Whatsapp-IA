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
    <div
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 220, position: 'relative' }}
    >
      {/* Barra roxa — automação e poder */}
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #7c3aed, #8b5cf6)' }}
      />

      <Handle type="target" position={Position.Left} />

      {/* Header */}
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#7c3aed' }} />
        <span className="flow-node-title">{nodeData.label || 'Ação'}</span>
        <span
          className="flow-node-badge"
          style={{ background: '#f5f3ff', color: '#5b21b6' }}
        >
          ACT
        </span>
      </div>

      {/* Corpo */}
      <div className="flow-node-body">
        <input
          className="flow-node-field nodrag"
          value={nodeData.action || ''}
          onChange={(e) => nodeData.onChange?.(id, { action: e.target.value })}
          placeholder="Nome da ação"
          style={{ width: '100%', padding: '7px 9px' }}
        />
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{
          right: -6,
          width: 10,
          height: 10,
          background: '#fff',
          border: '2px solid #7c3aed',
          borderRadius: '50%',
          cursor: 'crosshair',
          zIndex: 10,
        }}
      />
    </div>
  );
}
