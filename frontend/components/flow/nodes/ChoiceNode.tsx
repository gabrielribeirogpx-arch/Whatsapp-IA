'use client';

import { useEffect } from 'react';
import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type ChoiceButton = { id?: string; label?: string; value?: string; handleId?: string; next?: string };
type ChoiceNodeData = {
  label?: string;
  content?: string;
  buttons?: ChoiceButton[];
  display_mode?: 'buttons' | 'list';
  displayMode?: 'buttons' | 'list';
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ChoiceNode({ id, data, selected, isConnectable }: NodeProps) {
  const nodeData = (data || {}) as ChoiceNodeData;
  const displayMode = nodeData.display_mode || nodeData.displayMode || 'buttons';
  const buttons = (nodeData.buttons || []).map((button, index) => {
    const optionValue = button.value || button.label || button.id || `option_${index + 1}`;
    const label = button.label || button.value || `Opção ${index + 1}`;
    return { ...button, label, value: optionValue, handleId: button.handleId || toHandleId(optionValue, `option_${index + 1}`) };
  });


  useEffect(() => {
    buttons.forEach((button) => {
      console.debug('[CHOICE HANDLE RENDER]', {
        node_id: id,
        id: button.handleId,
        type: 'source',
        isConnectable,
        option_value: button.value,
      });
    });
  }, [buttons, id, isConnectable]);

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Escolha"
      emoji="🧭"
      badge={displayMode === 'list' ? 'LISTA' : 'BOTÕES'}
      badgeTone={{ background: '#fff7ed', color: '#c2410c' }}
      accent="linear-gradient(90deg, #f97316, #fb923c)"
      summary={truncateText(nodeData.content, 50, 'Escolha uma opção')}
      meta={displayMode === 'list' ? 'Lista WhatsApp' : 'Botões WhatsApp'}
      chips={buttons.map((button) => button.label || '')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
      isConnectable={isConnectable}
      sourceHandles={buttons.map((button) => ({ id: button.handleId, label: button.label, color: '#f97316', optionValue: button.value }))}
    />
  );
}
