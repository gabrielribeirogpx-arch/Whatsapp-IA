'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode, { fileNameFromUrl, truncateText } from './CompactFlowNode';

type RichMediaNodeData = {
  label?: string;
  media_url?: string;
  document_url?: string;
  filename?: string;
  caption?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

type RichMediaNodeProps = NodeProps & {
  mediaType?: 'image' | 'document';
};

const COLORS = {
  image: {
    accent: 'linear-gradient(90deg, #06b6d4, #22d3ee)',
    badgeTone: { background: '#ecfeff', color: '#0e7490' },
    badge: 'IMG',
    emoji: '🖼️',
    title: 'Imagem',
  },
  document: {
    accent: 'linear-gradient(90deg, #7c3aed, #a78bfa)',
    badgeTone: { background: '#f5f3ff', color: '#6d28d9' },
    badge: 'DOC',
    emoji: '📄',
    title: 'Documento',
  },
};

export default function RichMediaNode({ id, data, selected, mediaType = 'image' }: RichMediaNodeProps) {
  const nodeData = (data || {}) as RichMediaNodeData;
  const colors = COLORS[mediaType];
  const url = mediaType === 'image' ? nodeData.media_url : nodeData.document_url;
  const filename = mediaType === 'document'
    ? (nodeData.filename || fileNameFromUrl(url, 'documento.pdf'))
    : fileNameFromUrl(url, 'imagem não configurada');
  const caption = nodeData.caption ? `Legenda: ${truncateText(nodeData.caption, 25, '')}` : undefined;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title={colors.title}
      emoji={colors.emoji}
      badge={colors.badge}
      badgeTone={colors.badgeTone}
      accent={colors.accent}
      summary={filename}
      meta={caption}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
    />
  );
}

export function ImageNode(props: NodeProps) {
  return <RichMediaNode {...props} mediaType="image" />;
}

export function DocumentNode(props: NodeProps) {
  return <RichMediaNode {...props} mediaType="document" />;
}
