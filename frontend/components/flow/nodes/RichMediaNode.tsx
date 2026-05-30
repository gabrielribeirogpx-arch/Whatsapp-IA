'use client';

import { useState } from 'react';
import { Handle, NodeProps, Position } from 'reactflow';

import { apiFetch, parseApiResponse } from '@/lib/api';

type RichMediaNodeData = {
  label?: string;
  media_url?: string;
  document_url?: string;
  filename?: string;
  caption?: string;
  running?: boolean;
  isStart?: boolean;
  onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  onToggleStart?: (nodeId: string) => void;
};

type RichMediaNodeProps = NodeProps & {
  mediaType?: 'image' | 'document';
};

const COLORS = {
  image: { bar: 'linear-gradient(90deg, #06b6d4, #22d3ee)', dot: '#06b6d4', bg: '#ecfeff', text: '#0e7490', badge: 'IMG' },
  document: { bar: 'linear-gradient(90deg, #7c3aed, #a78bfa)', dot: '#7c3aed', bg: '#f5f3ff', text: '#6d28d9', badge: 'PDF' },
};

export default function RichMediaNode({ id, data, selected, mediaType = 'image' }: RichMediaNodeProps) {
  const nodeData = (data || {}) as RichMediaNodeData;
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const colors = COLORS[mediaType];
  const urlKey = mediaType === 'image' ? 'media_url' : 'document_url';
  const url = String(nodeData[urlKey] || '');

  const handleUpload = async (file: File | null) => {
    if (!file) return;
    setUploadError(null);
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await apiFetch('/api/flow-media/upload', { method: 'POST', body: formData });
      const result = await parseApiResponse<{ url: string; filename?: string }>(response);
      nodeData.onChange?.(id, { [urlKey]: result.url, ...(mediaType === 'document' && result.filename ? { filename: result.filename } : {}) });
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Falha ao enviar arquivo');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 260, position: 'relative' }}>
      <div className="flow-node-header-bar" style={{ background: colors.bar }} />
      <Handle type="target" position={Position.Left} />

      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: colors.dot }} />
        <span className="flow-node-title">{nodeData.label || (mediaType === 'image' ? 'Imagem' : 'Documento')}</span>
        <span className="flow-node-badge" style={{ background: colors.bg, color: colors.text }}>{colors.badge}</span>
        <button
          type="button"
          title={nodeData.isStart ? 'Bloco inicial' : 'Marcar como início'}
          onClick={(e) => { e.stopPropagation(); nodeData.onToggleStart?.(id); }}
          style={{ marginLeft: 'auto', background: nodeData.isStart ? '#16A34A' : 'transparent', border: nodeData.isStart ? 'none' : '1px solid #D1D5DB', borderRadius: 6, padding: '2px 6px', cursor: 'pointer', fontSize: 10, fontWeight: 600, color: nodeData.isStart ? '#fff' : '#9CA3AF' }}
        >
          {nodeData.isStart ? '▶ Início' : '▶'}
        </button>
      </div>

      <div className="flow-node-body" style={{ display: 'grid', gap: 8 }}>
        <input
          className="flow-node-field nodrag"
          type="file"
          accept={mediaType === 'image' ? 'image/*' : 'application/pdf'}
          disabled={isUploading}
          onChange={(e) => void handleUpload(e.target.files?.[0] || null)}
        />
        <input
          className="flow-node-field nodrag"
          value={url}
          onChange={(e) => nodeData.onChange?.(id, { [urlKey]: e.target.value })}
          placeholder={mediaType === 'image' ? 'URL da imagem' : 'URL do PDF'}
        />
        {isUploading && <span style={{ fontSize: 11, color: '#6B7280' }}>Enviando arquivo...</span>}
        {uploadError && <span style={{ fontSize: 11, color: '#dc2626' }}>{uploadError}</span>}
        {mediaType === 'document' && (
          <input
            className="flow-node-field nodrag"
            value={nodeData.filename || ''}
            onChange={(e) => nodeData.onChange?.(id, { filename: e.target.value })}
            placeholder="Nome do arquivo.pdf"
          />
        )}
        {mediaType === 'image' && url ? (
          <img src={url} alt="Preview" style={{ width: '100%', maxHeight: 120, objectFit: 'cover', borderRadius: 10, border: '1px solid #E5E7EB' }} />
        ) : null}
        {mediaType === 'document' && (nodeData.filename || url) ? (
          <div style={{ padding: 10, borderRadius: 10, border: '1px solid #E5E7EB', background: '#F9FAFB', fontSize: 12, color: '#374151' }}>
            📄 {nodeData.filename || url.split('/').pop() || 'documento.pdf'}
          </div>
        ) : null}
        <textarea
          className="flow-node-field nodrag"
          value={nodeData.caption || ''}
          onChange={(e) => nodeData.onChange?.(id, { caption: e.target.value })}
          placeholder="Legenda opcional"
          style={{ minHeight: 48, resize: 'vertical' }}
        />
      </div>

      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export function ImageNode(props: NodeProps) {
  return <RichMediaNode {...props} mediaType="image" />;
}

export function DocumentNode(props: NodeProps) {
  return <RichMediaNode {...props} mediaType="document" />;
}
