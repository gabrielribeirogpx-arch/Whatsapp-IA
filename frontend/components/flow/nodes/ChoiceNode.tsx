'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type ChoiceButton = { id?: string; label?: string; handleId?: string; next?: string };
type ChoiceNodeData = {
  label?: string;
  content?: string;
  buttons?: ChoiceButton[];
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ChoiceNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ChoiceNodeData;
  const buttons = (nodeData.buttons || []).map((button, index) => {
    const label = button.label || `Opção ${index + 1}`;
    return { ...button, label, handleId: button.handleId || toHandleId(label, `option_${index + 1}`) };
  });

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Escolha"
      emoji="🧭"
      badge="LOGIC"
      badgeTone={{ background: '#fff7ed', color: '#c2410c' }}
      accent="linear-gradient(90deg, #f97316, #fb923c)"
      summary={truncateText(nodeData.content, 50, 'Roteamento interno')}
      meta="Lógica interna do fluxo"
      chips={buttons.map((button) => button.label || '')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      sourceHandles={buttons.map((button) => ({ id: button.handleId, label: button.label, color: '#f97316' }))}
    />
  );
}
