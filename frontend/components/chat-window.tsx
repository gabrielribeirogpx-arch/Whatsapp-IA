import { FormEvent } from 'react';

import { Conversation, Message } from '../lib/types';
import MessageBubble from './message-bubble';

type ChatWindowProps = {
  selectedConversation?: Conversation;
  messages: Message[];
  messageText: string;
  onMessageTextChange: (value: string) => void;
  onSendMessage: (event: FormEvent<HTMLFormElement>) => void;
  onToggleTakeOver: () => void;
};

export default function ChatWindow({
  selectedConversation,
  messages,
  messageText,
  onMessageTextChange,
  onSendMessage,
  onToggleTakeOver
}: ChatWindowProps) {
  const statusLabel = selectedConversation?.status === 'human' ? 'Humano' : 'IA';

  return (
    <section className="chat-window">
      <header className="chat-header">
        <div>
          <h1>{selectedConversation?.name || 'Selecione uma conversa'}</h1>
          <p>{selectedConversation?.phone ? `${selectedConversation.phone} · ${statusLabel}` : 'Sem conversa selecionada'}</p>
        </div>

        <button type="button" className="secondary-button" onClick={onToggleTakeOver} disabled={!selectedConversation}>
          {selectedConversation?.status === 'human' ? 'Retomar com IA' : 'Assumir atendimento'}
        </button>
      </header>

      <main className="messages-panel">
        {selectedConversation ? (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        ) : (
          <p className="empty-state">Escolha uma conversa na lista para começar.</p>
        )}
      </main>

      <form className="message-composer" onSubmit={onSendMessage}>
        <input
          value={messageText}
          onChange={(event) => onMessageTextChange(event.target.value)}
          placeholder="Digite uma mensagem"
          maxLength={4096}
          disabled={!selectedConversation}
        />
        <button type="submit" className="primary-button" disabled={!selectedConversation || !messageText.trim()}>
          Enviar
        </button>
      </form>
    </section>
  );
}
