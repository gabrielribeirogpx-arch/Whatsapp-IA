'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type MediaNodeData = {
  label?: string;
  media_type?: 'image' | 'document' | 'audio' | 'video' | string;
  media_url?: string;
  caption?: string;
  filename?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
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

export default function MediaNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as MediaNodeData;
  const rawMediaType = String(nodeData.media_type || 'image');
  const mediaType = (['image', 'document', 'audio', 'video'].includes(rawMediaType) ? rawMediaType : 'image') as 'image' | 'document' | 'audio' | 'video';
  const iconByType = { image: '🖼️', document: '📄', audio: '🎵', video: '🎥' } as const;
  const labelByType = { image: 'Imagem', document: 'Documento', audio: 'Áudio', video: 'Vídeo' } as const;
  const icon = iconByType[mediaType];
  const typeLabel = labelByType[mediaType];
  const caption = String(nodeData.caption || '').trim();
  const filename = String(nodeData.filename || '').trim();
  const summaryParts = [typeLabel, caption || filename, compactUrl(nodeData.media_url)].filter(Boolean);

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Mídia"
      emoji={icon}
      badge="MEDIA"
      badgeTone={{ background: '#ecfeff', color: '#0e7490' }}
      accent="linear-gradient(90deg, #0891b2, #06b6d4)"
      summary={truncateText(summaryParts.join(' • '), 90, 'Mídia sem URL')}
      meta={mediaType === 'document' ? 'Documento/PDF' : typeLabel}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError || !String(nodeData.media_url || '').startsWith('https://')}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}
