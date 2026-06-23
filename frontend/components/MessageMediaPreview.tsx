import { FileText, ExternalLink, FileDown, Play } from 'lucide-react';
import type { ChatMessage } from '../lib/types';

type MediaKind = 'image' | 'video' | 'audio' | 'pdf' | 'file' | 'unknown';

type MediaInfo = {
  url: string;
  kind: MediaKind;
  mimeType?: string;
  filename?: string;
  caption: string;
  rawTextWasOnlyMediaUrl: boolean;
};

const MEDIA_SENT_PREFIX = /^\s*(?:📎\s*)?(?:m[ií]dia\s+enviada|media\s+sent)\s*:\s*/i;
const URL_RE = /https?:\/\/[^\s<>'")]+/i;

function sanitizeMediaUrl(value?: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(String(value).trim());
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return parsed.toString();
  } catch {
    return null;
  }
}

function extensionFromUrl(url: string): string {
  try {
    return new URL(url).pathname.split('.').pop()?.toLowerCase() || '';
  } catch {
    return '';
  }
}

function filenameFromUrl(url: string): string {
  try {
    const last = new URL(url).pathname.split('/').filter(Boolean).pop();
    return last ? decodeURIComponent(last) : 'arquivo';
  } catch {
    return 'arquivo';
  }
}

function mediaKindFrom(typeOrUrl?: string | null, url?: string): MediaKind {
  const value = String(typeOrUrl || '').toLowerCase();
  const ext = url ? extensionFromUrl(url) : '';
  if (value.startsWith('image/') || value === 'image' || ['jpg', 'jpeg', 'png', 'webp'].includes(ext)) return 'image';
  if (value.startsWith('video/') || value === 'video' || ['mp4', 'webm', 'mov'].includes(ext)) return 'video';
  if (value.startsWith('audio/') || value === 'audio' || ['mp3', 'ogg', 'mpeg'].includes(ext)) return 'audio';
  if (value === 'application/pdf' || value === 'pdf' || value === 'document' || ext === 'pdf') return 'pdf';
  if (url && ext) return 'file';
  return 'unknown';
}

export function getMessageMediaInfo(message: ChatMessage): MediaInfo | null {
  const directUrl = sanitizeMediaUrl(
    message.mediaUrl || message.attachmentUrl || message.fileUrl || null,
  );
  const text = String(message.text || '');
  const textUrl = sanitizeMediaUrl(text.match(URL_RE)?.[0] || null);
  const url = directUrl || textUrl;
  if (!url) return null;

  const type = message.mediaType || message.attachmentType || message.fileType || undefined;
  const kind = mediaKindFrom(type, url);
  if (kind === 'unknown') return {
    url,
    kind,
    mimeType: type || undefined,
    filename: message.filename || filenameFromUrl(url),
    caption: message.caption || text,
    rawTextWasOnlyMediaUrl: false,
  };

  const withoutPrefix = text.replace(MEDIA_SENT_PREFIX, '').trim();
  const rawTextWasOnlyMediaUrl = withoutPrefix === url || text.trim() === url;
  const caption = (message.caption || (rawTextWasOnlyMediaUrl ? '' : text.replace(url, '').replace(MEDIA_SENT_PREFIX, '').trim())).trim();
  return {
    url,
    kind,
    mimeType: type || undefined,
    filename: message.filename || filenameFromUrl(url),
    caption,
    rawTextWasOnlyMediaUrl,
  };
}

export function renderLinkedText(text: string) {
  const parts = String(text || '').split(/(https?:\/\/[^\s<>'")]+)/g);
  return parts.map((part, index) => {
    const safe = sanitizeMediaUrl(part);
    if (safe) return <a key={`${part}-${index}`} href={safe} target="_blank" rel="noreferrer">{part}</a>;
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

export default function MessageMediaPreview({ media, compact = false }: { media: MediaInfo; compact?: boolean }) {
  const boxStyle = { width: '100%', maxWidth: compact ? 280 : 360, borderRadius: 12, overflow: 'hidden' } as const;
  if (media.kind === 'image') {
    return <img src={media.url} alt={media.caption || media.filename || 'Mídia enviada'} style={{ ...boxStyle, display: 'block', maxHeight: compact ? 260 : 360, objectFit: 'contain' }} loading="lazy" />;
  }
  if (media.kind === 'video') {
    return (
      <div style={{ position: 'relative', ...boxStyle, background: '#0B141A' }}>
        <video controls src={media.url} preload="metadata" style={{ display: 'block', width: '100%', maxHeight: compact ? 260 : 360, objectFit: 'contain' }} />
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
          <span style={{ width: 42, height: 42, borderRadius: '50%', background: 'rgba(0,0,0,.35)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Play size={22} fill="currentColor" /></span>
        </div>
      </div>
    );
  }
  if (media.kind === 'audio') return <audio controls src={media.url} style={{ width: compact ? 240 : 320, maxWidth: '100%' }} />;

  const isPdf = media.kind === 'pdf';
  return (
    <a href={media.url} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 12, borderRadius: 12, background: 'rgba(255,255,255,.55)', color: 'inherit', textDecoration: 'none', maxWidth: compact ? 280 : 360 }}>
      {isPdf ? <FileText size={24} /> : <FileDown size={24} />}
      <span style={{ minWidth: 0, flex: 1 }}>
        <strong style={{ display: 'block', fontSize: 13 }}>{isPdf ? 'Documento PDF' : 'Arquivo'}</strong>
        <span style={{ display: 'block', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{media.filename}</span>
      </span>
      <ExternalLink size={16} />
    </a>
  );
}
