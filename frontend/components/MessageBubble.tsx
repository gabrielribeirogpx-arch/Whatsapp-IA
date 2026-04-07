import { ChatMessage } from '../lib/types';

type MessageBubbleProps = {
  message: ChatMessage;
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  return (
    <article className={`wa-message-bubble ${message.fromMe ? 'mine' : 'theirs'}`}>
      <p>{message.text}</p>
      <time>{message.time}</time>
    </article>
  );
}
