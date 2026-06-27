'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type MessageNodeData = {
  label?: string;
  content?: string;
  running?: boolean;
  isStart?: boolean;
  wait_for_reply?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function MessageNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MessageNodeData;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Mensagem"
      emoji="💬"
      badge="MSG"
      badgeTone={{ background: '#ecfdf5', color: '#047857' }}
      accent="linear-gradient(135deg, #10b981, #22c55e)"
      summary={nodeData.content || nodeData.label ? `Envia: “${truncateText(nodeData.content || nodeData.label, 44, 'mensagem')}”` : 'Envia uma mensagem ao contato'}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
      statusLabel={nodeData.wait_for_reply ? 'Aguardando resposta' : 'Envio configurado'}
    />
  );
}
