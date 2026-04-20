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
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
};

export default function ChoiceNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ChoiceNodeData;
  const buttons = (nodeData.buttons || []).map((button, index) => ({
    id: button.id || `${id}-button-${index + 1}`,
    label: button.label || '',
    handleId: button.handleId || button.label || `option_${index + 1}`,
    next: button.next,
  }));

  const updateButton = (index: number, label: string) => {
    const nextButtons = [...buttons];
    nextButtons[index] = { ...nextButtons[index], label };
    nodeData.onChange?.(id, { buttons: nextButtons });
  };

  const addButton = () => {
    const nextIndex = buttons.length + 1;
    nodeData.onChange?.(id, {
      buttons: [...buttons, { id: `${id}-button-${nextIndex}`, label: `Opção ${nextIndex}`, handleId: `option_${nextIndex}`, next: '' }],
    });
  };

  return (
    <div
      className={selected ? 'selected' : undefined}
      style={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, padding: 12, minWidth: 260 }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>{nodeData.label || 'Escolha'}</div>
      <textarea
        value={nodeData.content || ''}
        onChange={(event) => nodeData.onChange?.(id, { content: event.target.value })}
        placeholder="Pergunta para o usuário..."
        style={{ width: '100%', minHeight: 60, border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, resize: 'vertical' }}
      />

      <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
        {buttons.map((button, index) => (
          <input
            key={button.id}
            value={button.label || ''}
            onChange={(event) => updateButton(index, event.target.value)}
            placeholder={`Opção ${index + 1}`}
            style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: '6px 8px' }}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={addButton}
        style={{ marginTop: 8, width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: '#f9fafb' }}
      >
        + Adicionar opção
      </button>
      {buttons.map((button, index) => (
        <Handle
          key={`${button.id}-handle`}
          id={button.handleId}
          type="source"
          position={Position.Right}
          style={{ top: 124 + index * 34 }}
        />
      ))}
    </div>
  );
}
