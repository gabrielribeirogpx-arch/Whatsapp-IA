import { FormEvent } from 'react';

import { ChatMessage, Contact } from '../lib/types';
import MessageBubble from './MessageBubble';

type ChatWindowProps = {
  contact?: Contact;
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
};

export default function ChatWindow({ contact, messages, inputValue, onInputChange, onSend }: ChatWindowProps) {
  return (
    <section className="wa-chat-window">
      <header className="wa-chat-header">
        <h1>{contact?.name ?? 'Selecione um contato'}</h1>
        <p>{contact?.phone ?? 'Escolha um contato para iniciar'}</p>
      </header>

      <main className="wa-messages-panel">
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
