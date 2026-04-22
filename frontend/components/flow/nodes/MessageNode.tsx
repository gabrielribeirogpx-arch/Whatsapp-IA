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
