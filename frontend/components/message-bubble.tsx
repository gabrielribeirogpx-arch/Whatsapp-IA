import { Message } from '../lib/types';

type MessageBubbleProps = {
  message: Message;
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const timestamp = new Date(message.timestamp).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit'
  });

  return (
    <article className={`message-bubble ${message.from_me ? 'mine' : 'theirs'}`}>
      <p>{message.content}</p>
      <time dateTime={message.timestamp}>{timestamp}</time>
    </article>
  );
}
