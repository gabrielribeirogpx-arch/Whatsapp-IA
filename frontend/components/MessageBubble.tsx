import { ChatMessage } from '../lib/types';
import MessageMediaPreview, { getMessageMediaInfo, renderLinkedText } from './MessageMediaPreview';
import InteractiveMessageBubble, { normalizeInteractiveType } from './InteractiveMessageBubble';

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
  const interactiveType = normalizeInteractiveType(message.interactiveType);
  const isInteractive = Boolean(interactiveType || message.technicalPayload);

  return (
    <article className={`wa-message-bubble ${message.fromMe ? 'mine' : 'theirs'} ${message.isNew ? 'is-new' : ''}`}>
      {media && media.kind !== 'unknown' ? <MessageMediaPreview media={media} /> : null}
      {isInteractive && visibleText ? (
        <InteractiveMessageBubble title={visibleText} type={interactiveType} payload={message.technicalPayload} />
      ) : visibleText ? <p>{renderLinkedText(visibleText)}</p> : null}
      <time>
        {message.time}
        {message.fromMe ? (
          <span className={`wa-message-status ${status}`}>{statusIcon[status]}</span>
        ) : null}
      </time>
    </article>
  );
}
