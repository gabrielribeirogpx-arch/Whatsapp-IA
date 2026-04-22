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
      buttons: [
        ...buttons,
        { id: `${id}-button-${nextIndex}`, label: `Opção ${nextIndex}`, handleId: `option_${nextIndex}`, next: '' },
      ],
    });
  };

  // Altura de cada opção (padding 6px top+bottom + 1px border x2 + linha ~20px) = ~34px
  // Offset do topo até o início das opções:
  // barra (3px) + header (paddingTop 14 + dot ~20px + paddingBottom 8) + body padding (10px)
  // + textarea (minHeight 52 + marginBottom 8) + border = ~115px
  const OPTION_TOP_OFFSET = 115;
  const OPTION_HEIGHT = 34;

  return (
    <div
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 260, position: 'relative' }}
    >
      {/* Barra de identidade */}
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #f97316, #fb923c)' }}
      />

      <Handle type="target" position={Position.Left} />

      {/* Header */}
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#f97316' }} />
        <span className="flow-node-title">{nodeData.label || 'Escolha'}</span>
        <span
          className="flow-node-badge"
          style={{ background: '#fff7ed', color: '#c2410c' }}
        >
          CHOICE
        </span>
      </div>

      {/* Corpo */}
      <div className="flow-node-body">
        <textarea
          value={nodeData.content || ''}
          onChange={(e) => nodeData.onChange?.(id, { content: e.target.value })}
          placeholder="Pergunta para o usuário..."
          className="flow-node-field nodrag"
          style={{ minHeight: 52, resize: 'none', marginBottom: 8 }}
        />

        <div style={{ display: 'grid', gap: 5 }}>
          {buttons.map((button, index) => (
            <div key={button.id} className="flow-choice-option">
              <div className="flow-choice-option-dot" />
              <input
                className="nodrag"
                value={button.label || ''}
                onChange={(e) => updateButton(index, e.target.value)}
                placeholder={`Opção ${index + 1}`}
              />
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={addButton}
          className="flow-sidebar-button nodrag"
          style={{ marginTop: 8, width: '100%', justifyContent: 'center', fontSize: 12 }}
        >
          + Adicionar opção
        </button>
      </div>

      {/* Handles posicionados absolutamente, calculados por índice */}
      {buttons.map((button, index) => (
        <Handle
          key={button.handleId}
          id={button.handleId}
          type="source"
          position={Position.Right}
          style={{
            top: OPTION_TOP_OFFSET + index * (OPTION_HEIGHT + 5) + OPTION_HEIGHT / 2,
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
      ))}
    </div>
  );
}
