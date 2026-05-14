import { ChatMessage } from '../lib/types';

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

  return (
    <article className={`wa-message-bubble ${message.fromMe ? 'mine' : 'theirs'} ${message.isNew ? 'is-new' : ''}`}>
      <p>{message.text}</p>
      <time>
        {message.time}
        {message.fromMe ? (
          <span className={`wa-message-status ${status}`}>{statusIcon[status]}</span>
        ) : null}
      </time>
    </article>
  );
}
