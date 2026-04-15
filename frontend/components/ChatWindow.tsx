import { FormEvent, useEffect, useRef, useState } from 'react';
import { ChatMessage, Contact } from '../lib/types';
import { IconMenu } from './icons';
import Avatar from './Avatar';
import MessageBubble from './MessageBubble';

type ChatWindowProps = {
  contact?: Contact;
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onToggleSidebar: () => void;
};

export default function ChatWindow({
  contact,
  messages,
  inputValue,
  onInputChange,
  onSend,
  onToggleSidebar
}: ChatWindowProps) {
  const messagesRef = useRef<HTMLElement | null>(null);
  const [, setStatusTick] = useState(0);

  useEffect(() => {
    if (!messagesRef.current) return;

    messagesRef.current.scrollTo({
      top: messagesRef.current.scrollHeight,
      behavior: 'smooth'
    });
  }, [messages]);

  useEffect(() => {
    const interval = setInterval(() => {
      setStatusTick((current) => current + 1);
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  function getStatus(lastInteraction?: string | null) {
    if (!lastInteraction) return 'offline';

    const diff = Date.now() - new Date(lastInteraction).getTime();

    if (diff < 30000) return 'online';
    if (diff < 300000) return 'recent';
    return 'offline';
  }

  function getSeenMinutes(lastInteraction?: string | null) {
    if (!lastInteraction) return 'Visto há alguns minutos';

    const diff = Date.now() - new Date(lastInteraction).getTime();
    if (Number.isNaN(diff) || diff <= 0) return 'Visto há alguns minutos';

    const minutes = Math.max(1, Math.floor(diff / 60000));
    return `Visto há ${minutes} minuto${minutes > 1 ? 's' : ''}`;
  }

  const status = getStatus(contact?.lastInteraction);
  const statusText = contact?.isTyping
    ? 'Digitando...'
    : status === 'online'
      ? 'Online agora'
      : status === 'recent'
        ? 'Ativo há poucos minutos'
        : getSeenMinutes(contact?.lastInteraction);
  const statusClass = contact?.isTyping ? 'typing' : status;

  return (
    <section className="wa-chat-window">
      <header className="wa-chat-header">
        <button type="button" className="wa-mobile-menu" onClick={onToggleSidebar} aria-label="Abrir conversas">
          <IconMenu width={20} />
        </button>

        {contact ? (
          <div className="wa-chat-contact">
            <Avatar name={contact.name} avatarUrl={contact.avatarUrl} phone={contact.phone} />
            <div>
              <h1>{contact.name || contact.phone}</h1>
              <p className={`wa-contact-status ${statusClass}`}>
                <span className="wa-status-dot" aria-hidden="true" />
                {statusText}
              </p>
            </div>
          </div>
        ) : (
          <div>
            <h1>Selecione um contato</h1>
            <p>Escolha uma conversa para começar.</p>
          </div>
        )}
      </header>

      <main className="wa-messages-panel" ref={messagesRef}>
        {contact ? (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        ) : (
          <p className="empty-state">Nenhuma conversa selecionada.</p>
        )}
      </main>

      <form className="wa-message-composer" onSubmit={onSend}>
        <input
          value={inputValue}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Digite uma mensagem"
          disabled={!contact}
        />
        <button type="submit" className="primary-button" disabled={!contact || !inputValue.trim()}>
          Enviar
        </button>
      </form>
    </section>
  );
}
