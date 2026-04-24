'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ConditionNodeData = {
  label?: string;
  condition?: string;
  running?: boolean;
  isStart?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  onToggleStart?: (nodeId: string) => void;
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
        <button
          type="button"
          title={nodeData.isStart ? 'Node inicial' : 'Marcar como início'}
          onClick={(e) => {
            e.stopPropagation();
            nodeData.onToggleStart?.(id);
          }}
          style={{
            marginLeft: 'auto',
            background: nodeData.isStart ? '#16A34A' : 'transparent',
            border: nodeData.isStart ? 'none' : '1px solid #D1D5DB',
            borderRadius: 6,
            padding: '2px 6px',
            cursor: 'pointer',
            fontSize: 10,
            fontWeight: 600,
            color: nodeData.isStart ? '#fff' : '#9CA3AF',
            display: 'flex',
            alignItems: 'center',
            gap: 3,
            transition: 'all 0.15s',
          }}
        >
          {nodeData.isStart ? '▶ Início' : '▶'}
        </button>
      </div>

      {/* Corpo */}
      <div className="flow-node-body">
        <input
          className="flow-node-field nodrag"
          value={nodeData.condition || ''}
          onChange={(e) => nodeData.onChange?.(id, { condition: e.target.value })}
          placeholder="Ex.: plano, preço, valor, quanto custa"
          style={{ width: '100%', padding: '7px 9px' }}
        />
        <div style={{ marginTop: 5, fontSize: 10.5, color: '#a8b0a0', lineHeight: 1.4 }}>
          Separe múltiplas palavras por vírgula.<br />
          Match se a mensagem contiver qualquer uma.
        </div>
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
