'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type DelayNodeData = {
  label?: string;
  content?: string;
  delay?: string | number;
  seconds?: string | number;
  show_typing?: boolean;
  typing_duration_mode?: 'delay' | 'auto';
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function DelayNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as DelayNodeData;
  const value = nodeData.seconds || nodeData.delay || nodeData.content || '3';

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Aguardar"
      emoji="⏱️"
      badge="WAIT"
      badgeTone={{ background: '#ecfeff', color: '#0e7490' }}
      accent="linear-gradient(90deg, #0891b2, #06b6d4)"
      summary={`Aguardar ${value}s`}
      meta={nodeData.show_typing ? 'Pausa + digitando no WhatsApp' : 'Pausa no fluxo'}
      chips={nodeData.show_typing && nodeData.typing_duration_mode === 'auto' ? ['Digitando automático'] : []}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
      statusLabel={nodeData.show_typing ? 'Digitando antes de seguir' : 'Pausa programada'}
    />
  );
}
