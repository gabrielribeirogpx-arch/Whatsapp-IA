'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

import { getConversations, getMessages, sendMessage, streamMessagesUrl, toggleTakeOver } from '../lib/api';
import { Conversation, Message } from '../lib/types';

export default function ChatShell() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedPhone, setSelectedPhone] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');

  const selectedConversation = useMemo(
    () => conversations.find((item) => item.phone === selectedPhone),
    [conversations, selectedPhone]
  );

  async function refreshConversations() {
    const data = await getConversations();
    setConversations(data);
    if (!selectedPhone && data[0]?.phone) setSelectedPhone(data[0].phone);
  }

  useEffect(() => {
    refreshConversations();
  }, []);

  useEffect(() => {
    if (!selectedPhone) return;
    getMessages(selectedPhone).then(setMessages).catch(console.error);

    const source = new EventSource(streamMessagesUrl(selectedPhone));
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data?.event === 'message') {
        setMessages((prev) => [...prev, data.message]);
        refreshConversations();
      }
    };

    return () => source.close();
  }, [selectedPhone]);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!selectedPhone || !text.trim()) return;
    await sendMessage(selectedPhone, text);
    setText('');
    await refreshConversations();
  }

  async function onTakeOver() {
    if (!selectedPhone) return;
    await toggleTakeOver(selectedPhone);
    await refreshConversations();
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        {conversations.map((conv) => (
          <div
            key={conv.phone}
            className={`conversation-item ${conv.phone === selectedPhone ? 'active' : ''}`}
            onClick={() => setSelectedPhone(conv.phone)}
          >
            <div><strong>{conv.name || conv.phone}</strong></div>
            <div className="muted">{conv.last_message || 'Sem mensagens ainda'}</div>
            <span className={`badge ${conv.assigned_to === 'HUMANO' ? 'human' : ''}`}>{conv.assigned_to}</span>
          </div>
        ))}
      </aside>

      <section className="chat-area">
        <header className="chat-header">
          <div>
            <strong>{selectedConversation?.name || 'Selecione uma conversa'}</strong>
            <div className="muted">{selectedConversation?.phone}</div>
          </div>
          <button onClick={onTakeOver}>Assumir atendimento</button>
        </header>

        <div className="messages">
          {messages.map((message) => (
            <div key={message.id} className={`bubble ${message.from_me ? 'mine' : 'theirs'}`}>
              <div>{message.content}</div>
              <div className="muted">{new Date(message.timestamp).toLocaleString('pt-BR')}</div>
            </div>
          ))}
        </div>

        <form className="composer" onSubmit={onSend}>
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Digite uma mensagem"
            maxLength={4096}
          />
          <button type="submit" className="primary">Enviar</button>
        </form>
      </section>
    </div>
  );
}
