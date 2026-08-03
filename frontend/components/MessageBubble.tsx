import { ChatMessage } from '../lib/types';
import MessageMediaPreview, { getMessageMediaInfo, renderLinkedText } from './MessageMediaPreview';

type MessageBubbleProps = {
  message: ChatMessage;
};

const statusIcon: Record<'sent' | 'delivered' | 'read', string> = {
  sent: '✓',
  delivered: '✓✓',
  read: '✓✓'
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const status = message.status ?? 'sent';
  const media = getMessageMediaInfo(message);
  const visibleText = media?.caption ?? message.text;

  return (
    <article className={`wa-message-bubble ${message.fromMe ? 'mine' : 'theirs'} ${message.isNew ? 'is-new' : ''}`}>
      {media && media.kind !== 'unknown' ? <MessageMediaPreview media={media} /> : null}
      {visibleText ? <p>{renderLinkedText(visibleText)}</p> : null}
      {message.technicalPayload ? (
        <details className="wa-message-technical-details">
          <summary>Detalhes</summary>
          <div><strong>Payload:</strong> <code>{message.technicalPayload}</code></div>
        </details>
      ) : null}
      <time>
        {message.time}
        {message.fromMe ? (
          <span className={`wa-message-status ${status}`}>{statusIcon[status]}</span>
        ) : null}
      </time>
    </article>
  );
}
