'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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
  isStart?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  onToggleStart?: (nodeId: string) => void;
};

const toHandleId = (value: string, fallback: string) => {
  const normalized = value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};

// Calcula tops estimados baseado na estrutura real do node:
// barra(3) + header(paddingTop14 + altura~28 + paddingBottom8) = ~53px
// body padding top (10px) + textarea (minHeight52 + marginBottom8) = ~70px
// total até primeira opção: ~123px
// cada opção: height~28px + gap5px = ~33px
function estimateTops(count: number): number[] {
  const FIRST_OPTION_TOP = 123;
  const OPTION_STEP = 33;
  return Array.from({ length: count }, (_, i) =>
    FIRST_OPTION_TOP + i * OPTION_STEP + 14 // +14 = metade da altura da opção
  );
}

export default function ChoiceNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ChoiceNodeData;
  const buttons = (nodeData.buttons || []).map((button, index) => ({
    id: button.id || `${id}-button-${index + 1}`,
    label: button.label || '',
    handleId: toHandleId(button.handleId || button.label || '', `option_${index + 1}`),
    next: button.next,
  }));

  const optionRefs = useRef<(HTMLDivElement | null)[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Inicia com estimativa para evitar flash no topo
  const [handleTops, setHandleTops] = useState<number[]>(() => estimateTops(buttons.length));

  // Atualiza estimativa quando muda o número de botões
  useEffect(() => {
    setHandleTops(estimateTops(buttons.length));
  }, [buttons.length]);

  const measurePositions = () => {
    if (!containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    if (containerRect.height === 0) return;
    const tops = optionRefs.current
      .slice(0, buttons.length)
      .map((ref) => {
        if (!ref) return null;
        const rect = ref.getBoundingClientRect();
        if (rect.height === 0) return null;
        return rect.top - containerRect.top + rect.height / 2;
      });
    // Só atualiza se todos os valores são válidos
    if (tops.every((t) => t !== null && t > 0)) {
      setHandleTops(tops as number[]);
    }
  };

  // useLayoutEffect para medir antes do paint — evita flash
  useLayoutEffect(() => {
    measurePositions();
    const t1 = setTimeout(measurePositions, 50);
    const t2 = setTimeout(measurePositions, 200);

    const observer = new ResizeObserver(measurePositions);
    if (containerRef.current) observer.observe(containerRef.current);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      observer.disconnect();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buttons.length, nodeData.content]);

  const updateButton = (index: number, label: string) => {
    const nextButtons = [...buttons];
    nextButtons[index] = {
      ...nextButtons[index],
      label,
      handleId: toHandleId(label, `option_${index + 1}`),
    };
    nodeData.onChange?.(id, { buttons: nextButtons });
  };

  const removeButton = (index: number) => {
    const nextButtons = buttons.filter((_, i) => i !== index);
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

  return (
    <div
      ref={containerRef}
      className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`}
      style={{ minWidth: 260, position: 'relative' }}
    >
      <div
        className="flow-node-header-bar"
        style={{ background: 'linear-gradient(90deg, #f97316, #fb923c)' }}
      />

      <Handle type="target" position={Position.Left} />

      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#f97316' }} />
        <span className="flow-node-title">{nodeData.label || 'Escolha'}</span>
        <span className="flow-node-badge" style={{ background: '#fff7ed', color: '#c2410c' }}>
          CHOICE
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
            <div
              key={button.id}
              ref={(el) => { optionRefs.current[index] = el; }}
              className="flow-choice-option"
              style={{ position: 'relative', paddingRight: 24 }}
            >
              <div className="flow-choice-option-dot" />
              <input
                className="nodrag"
                value={button.label || ''}
                onChange={(e) => updateButton(index, e.target.value)}
                placeholder={`Opção ${index + 1}`}
              />
              {buttons.length > 1 && (
                <button
                  type="button"
                  className="nodrag"
                  onClick={() => removeButton(index)}
                  title="Remover opção"
                  style={{
                    position: 'absolute',
                    right: 4,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    border: 'none',
                    background: 'transparent',
                    color: '#d1d5db',
                    cursor: 'pointer',
                    fontSize: 14,
                    lineHeight: 1,
                    padding: '2px 4px',
                    borderRadius: 4,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'color 0.15s',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#ef4444'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#d1d5db'; }}
                >
                  ×
                </button>
              )}
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

      {buttons.map((button, index) => {
        // Altura base: header (40px) + textarea (60px + 8px margin) + margem antes dos botões (8px) = 116px
        // Cada botão tem altura ~34px (padding + border + input)
        // Handle deve ficar no centro vertical de cada botão
        const baseOffset = 116;
        const buttonHeight = 34;
        const handleTop = baseOffset + (index * buttonHeight) + (buttonHeight / 2);

        return (
          <Handle
            key={button.handleId}
            id={button.handleId}
            type="source"
            position={Position.Right}
            style={{
              top: handleTop,
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
        );
      })}
    </div>
  );
}
