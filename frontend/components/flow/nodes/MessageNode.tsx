'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type MessageNodeData = {
  label?: string;
  content?: string;
  running?: boolean;
  isStart?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  onToggleStart?: (nodeId: string) => void;
};

export default function MessageNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MessageNodeData;

  return (
    <div
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 240, position: 'relative' }}
    >
      {/* Barra de identidade — azul-índigo para Mensagem */}
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #4f46e5, #6366f1)' }}
      />

      <Handle type="target" position={Position.Left} />

      {/* Header */}
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#4f46e5' }} />
        <span className="flow-node-title">{nodeData.label || 'Mensagem'}</span>
        <span
          className="flow-node-badge"
          style={{ background: '#eef2ff', color: '#4338ca' }}
        >
          MSG
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
        <textarea
          value={nodeData.content || ''}
          onChange={(e) => nodeData.onChange?.(id, { content: e.target.value })}
          placeholder="Digite a mensagem..."
          className="flow-node-field"
          style={{ minHeight: 72, resize: 'vertical' }}
        />
      </div>

      <Handle type="source" position={Position.Right} />
    </div>
  );
}
