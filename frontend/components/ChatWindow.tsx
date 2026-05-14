import { FormEvent, useEffect, useMemo, useRef } from 'react';
import { ChatMessage, Contact, ConversationMode } from '../lib/types';
import { IconMenu } from './icons';
import Avatar from './Avatar';
import MessageBubble from './MessageBubble';
import ConversationModeSelector from './ConversationModeSelector';

type ChatWindowProps = {
  contact?: Contact;
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onToggleSidebar: () => void;
  mode: ConversationMode;
  modeUpdating?: boolean;
  modeNotice?: string;
  modeError?: string;
  emptyStateMessage?: string;
  onModeChange: (mode: ConversationMode) => void;
};

function formatDateDivider(dateIso?: string) {
  if (!dateIso) return '';
  const date = new Date(dateIso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(date, today)) return 'Hoje';
  if (same(date, yesterday)) return 'Ontem';
  return date.toLocaleDateString('pt-BR', { weekday: 'long' });
}

export default function ChatWindow(props: ChatWindowProps) {
  const { contact, messages, inputValue, onInputChange, onSend, onToggleSidebar, mode, modeUpdating = false, modeNotice, modeError, emptyStateMessage, onModeChange } = props;
  const messagesRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!messagesRef.current) return;
    const el = messagesRef.current;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom < 120) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [messages]);

  const grouped = useMemo(() => {
    const out: Array<{ divider?: string; message?: ChatMessage; key: string }> = [];
    let lastDivider = '';
    messages.forEach((message) => {
      const divider = formatDateDivider(message.createdAt);
      if (divider && divider !== lastDivider) {
        out.push({ divider, key: `d-${message.id}` });
        lastDivider = divider;
      }
      out.push({ message, key: message.id });
    });
    return out;
  }, [messages]);

  const statusText = contact?.isTyping ? 'digitando...' : contact?.isOnline ? 'Online agora' : 'Offline';

  return <section className="wa-chat-window"><header className="wa-chat-header"><button type="button" className="wa-mobile-menu" onClick={onToggleSidebar} aria-label="Abrir conversas"><IconMenu width={20} /></button>{contact ? <><div className="wa-chat-contact"><Avatar name={contact.name} avatarUrl={contact.avatarUrl} phone={contact.phone} /><div><h1>{contact.name || contact.phone}</h1><p className={`wa-contact-status ${contact.isTyping ? 'typing' : contact.isOnline ? 'online' : 'away'}`}><span className="wa-status-dot" aria-hidden="true" />{statusText}</p></div></div><div className="wa-chat-actions"><ConversationModeSelector mode={mode} loading={modeUpdating} disabled={!contact} onChange={onModeChange} />{modeUpdating ? <p className="wa-mode-feedback">Atualizando modo...</p> : null}{!modeUpdating && modeNotice ? <p className="wa-mode-feedback success">{modeNotice}</p> : null}{!modeUpdating && modeError ? <p className="wa-mode-feedback error">{modeError}</p> : null}</div></> : <div><h1>Selecione um contato</h1><p>{emptyStateMessage || 'Escolha uma conversa para começar.'}</p></div>}</header><main className="wa-messages-panel" ref={messagesRef}>{contact ? grouped.map((item) => item.divider ? <div key={item.key} className="wa-date-divider"><span>{item.divider}</span></div> : <MessageBubble key={item.key} message={item.message!} />) : <p className="empty-state">Nenhuma conversa selecionada.</p>}{contact?.isTyping ? <div className="wa-typing-indicator"><span /><span /><span /> digitando...</div> : null}</main><form className="wa-message-composer" onSubmit={onSend}><input value={inputValue} onChange={(event) => onInputChange(event.target.value)} placeholder="Digite uma mensagem…" disabled={!contact} /><button type="submit" className="primary-button wa-send-btn" disabled={!contact || !inputValue.trim()}>Enviar</button></form></section>;
}
