'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ButtonItem = { id?: string; label?: string; handleId?: string };
type ButtonsNodeData = {
  label?: string;
  body_text?: string;
  buttons?: ButtonItem[];
  running?: boolean;
  isStart?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  onToggleStart?: (nodeId: string) => void;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ButtonsNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ButtonsNodeData;
  const buttons = (nodeData.buttons || []).slice(0, 3).map((button, index) => {
    const label = button.label || `Botão ${index + 1}`;
    return { id: button.id || `${id}-button-${index + 1}`, label, handleId: button.handleId || toHandleId(label, `button_${index + 1}`) };
  });

  const updateButton = (index: number, label: string) => {
    const next = [...buttons];
    next[index] = { ...next[index], label, handleId: toHandleId(label, `button_${index + 1}`) };
    nodeData.onChange?.(id, { buttons: next });
  };

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 270, position: 'relative' }}>
      <div className="flow-node-header-bar" style={{ background: 'linear-gradient(90deg, #16a34a, #22c55e)' }} />
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#16a34a' }} />
        <span className="flow-node-title">{nodeData.label || 'Botões'}</span>
        <span className="flow-node-badge" style={{ background: '#dcfce7', color: '#166534' }}>BUTTONS</span>
        <button type="button" title={nodeData.isStart ? 'Bloco inicial' : 'Marcar como início'} onClick={(e) => { e.stopPropagation(); nodeData.onToggleStart?.(id); }} style={{ marginLeft: 'auto', background: nodeData.isStart ? '#16A34A' : 'transparent', border: nodeData.isStart ? 'none' : '1px solid #D1D5DB', borderRadius: 6, padding: '2px 6px', cursor: 'pointer', fontSize: 10, fontWeight: 600, color: nodeData.isStart ? '#fff' : '#9CA3AF' }}>{nodeData.isStart ? '▶ Início' : '▶'}</button>
      </div>
      <div className="flow-node-body" style={{ display: 'grid', gap: 8 }}>
        <textarea className="flow-node-field nodrag" value={nodeData.body_text || ''} onChange={(e) => nodeData.onChange?.(id, { body_text: e.target.value })} placeholder="Texto da mensagem" style={{ minHeight: 54, resize: 'vertical' }} />
        {buttons.map((button, index) => (
          <input key={button.id} className="flow-node-field nodrag" value={button.label} onChange={(e) => updateButton(index, e.target.value)} placeholder={`Botão ${index + 1}`} maxLength={20} />
        ))}
        <button type="button" className="flow-sidebar-button nodrag" disabled={buttons.length >= 3} onClick={() => nodeData.onChange?.(id, { buttons: [...buttons, { id: `${id}-button-${buttons.length + 1}`, label: `Botão ${buttons.length + 1}`, handleId: `button_${buttons.length + 1}` }] })} style={{ width: '100%', justifyContent: 'center', fontSize: 12, opacity: buttons.length >= 3 ? 0.5 : 1 }}>
          + Adicionar botão ({buttons.length}/3)
        </button>
      </div>
      {buttons.map((button, index) => (
        <Handle key={button.handleId} id={button.handleId} type="source" position={Position.Right} style={{ top: 132 + index * 38, right: -6, width: 10, height: 10, background: '#fff', border: '2px solid #16a34a' }} />
      ))}
    </div>
  );
}
