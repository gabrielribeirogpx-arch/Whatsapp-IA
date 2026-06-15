'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type CtaUrlNodeData = {
  content?: string;
  text?: string;
  message?: string;
  button_text?: string;
  url?: string;
  running?: boolean;
  isStart?: boolean;
  hasValidationError?: boolean;
  onToggleStart?: (nodeId: string) => void;
};

const compactUrl = (value?: string) => {
  const text = String(value || '').trim();
  if (!text) return 'URL obrigatória';
  try {
    const url = new URL(text);
    return `${url.hostname}${url.pathname}`.replace(/\/$/, '') || text;
  } catch {
    return text;
  }
};

export default function CtaUrlNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as CtaUrlNodeData;
  const message = String(nodeData.content || nodeData.text || nodeData.message || '').trim();
  const buttonText = String(nodeData.button_text || '').trim();
  const url = String(nodeData.url || '').trim();
  const hasInvalidButton = buttonText.length === 0 || buttonText.length > 20;
  const hasInvalidUrl = !url.startsWith('https://');

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="CTA / Link"
      emoji="🔗"
      badge="LINK"
      badgeTone={{ background: '#eef2ff', color: '#4338ca' }}
      accent="linear-gradient(90deg, #4f46e5, #7c3aed)"
      summary={truncateText(message, 64, 'Mensagem obrigatória')}
      meta={`Botão: ${truncateText(buttonText, 24, 'Obrigatório')} • ${compactUrl(url)}`}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError || !message || hasInvalidButton || hasInvalidUrl}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
    />
  );
}
