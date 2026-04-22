'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ChoiceButton = {
  id: string;
  label: string;
  handleId: string;
  next?: string;
};

type ChoiceNodeData = {
  label?: string;
  content?: string;
  buttons?: ChoiceButton[];
  running?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

const toHandleId = (value: string, fallback: string) => {
  const normalized = value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};

export default function ChoiceNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ChoiceNodeData;
  const buttons = (nodeData.buttons || []).map((button, index) => ({
    id: button.id || `${id}-button-${index + 1}`,
    label: button.label || '',
    handleId: toHandleId(button.handleId || button.label || '', `option_${index + 1}`),
    next: button.next,
  }));

  const updateButton = (index: number, label: string) => {
    const nextButtons = [...buttons];
    nextButtons[index] = {
      ...nextButtons[index],
      label,
      handleId: toHandleId(label, `option_${index + 1}`),
    };
    nodeData.onChange?.(id, { buttons: nextButtons });
  };

  const addButton = () => {
    const nextIndex = buttons.length + 1;
    nodeData.onChange?.(id, {
      buttons: [...buttons, { id: `${id}-button-${nextIndex}`, label: `Opção ${nextIndex}`, handleId: `option_${nextIndex}`, next: '' }],
    });
  };

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 260 }}>
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Escolha'}</div>
      <textarea
        value={nodeData.content || ''}
        onChange={(event) => nodeData.onChange?.(id, { content: event.target.value })}
        placeholder="Pergunta para o usuário..."
        className="flow-node-field"
        style={{ width: '100%', minHeight: 60, resize: 'vertical' }}
      />

      <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
        {buttons.map((button, index) => (
          <input
            key={button.id}
            value={button.label || ''}
            onChange={(event) => updateButton(index, event.target.value)}
            placeholder={`Opção ${index + 1}`}
            className="flow-node-field"
            style={{ padding: '6px 8px' }}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={addButton}
        className="flow-sidebar-button"
        style={{ marginTop: 8, width: '100%', justifyContent: 'center', padding: '6px 10px', fontSize: 13 }}
      >
        + Adicionar opção
      </button>
      {buttons.map((button, index) => (
        <Handle
          key={button.handleId}
          id={button.handleId}
          type="source"
          position={Position.Right}
          style={{ top: 124 + index * 34 }}
        />
      ))}
    </div>
  );
}
