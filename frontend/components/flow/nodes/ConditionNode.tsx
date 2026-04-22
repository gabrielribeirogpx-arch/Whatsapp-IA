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
    <div
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 240, position: 'relative' }}
    >
      {/* Barra âmbar — lógica e cautela */}
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #d97706, #f59e0b)' }}
      />

      <Handle type="target" position={Position.Left} />

      {/* Header */}
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#d97706' }} />
        <span className="flow-node-title">{nodeData.label || 'Condição'}</span>
        <span
          className="flow-node-badge"
          style={{ background: '#fef3c7', color: '#92400e' }}
        >
          IF
        </span>
      </div>

      {/* Corpo */}
      <div className="flow-node-body">
        <input
          className="flow-node-field nodrag"
          value={nodeData.condition || ''}
          onChange={(e) => nodeData.onChange?.(id, { condition: e.target.value })}
          placeholder="Ex.: mensagem contém 'plano'"
          style={{ width: '100%', padding: '7px 9px' }}
        />
        {/* Labels dos handles */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: '#16a34a', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 4, padding: '2px 6px' }}>
            Sim →
          </span>
          <span style={{ fontSize: 10, fontWeight: 600, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 4, padding: '2px 6px' }}>
            Não →
          </span>
        </div>
      </div>

      {/* Handle Sim (true) */}
      <Handle
        type="source"
        position={Position.Right}
        id="true"
        style={{
          top: '38%',
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
      {/* Handle Não (false) */}
      <Handle
        type="source"
        position={Position.Right}
        id="false"
        style={{
          top: '68%',
          right: -6,
          width: 10,
          height: 10,
          background: '#fff',
          border: '2px solid #dc2626',
          borderRadius: '50%',
          cursor: 'crosshair',
          zIndex: 10,
        }}
      />
    </div>
  );
}
