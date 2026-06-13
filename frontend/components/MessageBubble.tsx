import { ChatMessage } from '../lib/types';

type MessageBubbleProps = {
  message: ChatMessage;
};

const statusIcon: Record<'sent' | 'delivered' | 'read', string> = {
  sent: '✓',
  delivered: '✓✓',
  read: '✓✓'
};

const renderMessageText = (text: string) => {
  const parts = String(text || '').split(/(https:\/\/\S+)/g);
  return parts.map((part, index) => {
    if (part.startsWith('https://')) {
      return (
        <a key={`${part}-${index}`} href={part} target="_blank" rel="noreferrer">
          {part}
        </a>
      );
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const status = message.status ?? 'sent';
  const isMedia = message.mediaType || message.mediaUrl || message.text.includes('📎 Mídia enviada');

  return (
    <article className={`wa-message-bubble ${message.fromMe ? 'mine' : 'theirs'} ${message.isNew ? 'is-new' : ''}`}>
      <p>{isMedia ? '📎 ' : null}{renderMessageText(message.text || (message.mediaUrl ? `Mídia enviada: ${message.mediaUrl}` : 'Mídia enviada'))}</p>
      <time>
        {message.time}
        {message.fromMe ? (
          <span className={`wa-message-status ${status}`}>{statusIcon[status]}</span>
        ) : null}
      </time>
    </article>
  );
}
