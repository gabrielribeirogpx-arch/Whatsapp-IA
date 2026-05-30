'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type ButtonItem = { id?: string; label?: string; handleId?: string };
type ButtonsNodeData = {
  label?: string;
  body_text?: string;
  buttons?: ButtonItem[];
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ButtonsNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ButtonsNodeData;
  const buttons = (nodeData.buttons || []).slice(0, 3).map((button, index) => {
    const label = button.label || `Botão ${index + 1}`;
    return { ...button, label, handleId: button.handleId || toHandleId(label, `button_${index + 1}`) };
  });

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Botões"
      emoji="🔘"
      badge="BUTTONS"
      badgeTone={{ background: '#dcfce7', color: '#166534' }}
      accent="linear-gradient(90deg, #16a34a, #22c55e)"
      summary={`${buttons.length} opções configuradas`}
      chips={buttons.map((button) => button.label || '')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      sourceHandles={buttons.map((button) => ({ id: button.handleId, label: button.label, color: '#16a34a' }))}
    />
  );
}
