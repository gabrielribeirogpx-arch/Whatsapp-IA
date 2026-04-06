'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

import { getConversations, getMessages, sendMessage, streamMessagesUrl, tenantLogin, toggleTakeOver } from '../lib/api';
import { Conversation, Message, TenantAuth, TenantSession } from '../lib/types';

const STORAGE_KEY = 'tenant_auth';

export default function ChatShell() {
  const [auth, setAuth] = useState<TenantAuth | null>(null);
  const [session, setSession] = useState<TenantSession | null>(null);
  const [slugInput, setSlugInput] = useState('default');
  const [passwordInput, setPasswordInput] = useState('admin123');
  const [loginError, setLoginError] = useState('');

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedPhone, setSelectedPhone] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');

  const selectedConversation = useMemo(
    () => conversations.find((item) => item.phone === selectedPhone),
    [conversations, selectedPhone]
  );

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return;
    try {
      const parsed = JSON.parse(saved) as TenantAuth;
      setAuth(parsed);
      tenantLogin(parsed).then(setSession).catch(() => localStorage.removeItem(STORAGE_KEY));
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  async function onLogin(event: FormEvent) {
    event.preventDefault();
    const nextAuth = { slug: slugInput.trim(), password: passwordInput.trim() };
    try {
      const tenantSession = await tenantLogin(nextAuth);
      setAuth(nextAuth);
      setSession(tenantSession);
      setLoginError('');
      localStorage.setItem(STORAGE_KEY, JSON.stringify(nextAuth));
    } catch {
      setLoginError('Credenciais inválidas para tenant.');
    }
  }

  async function refreshConversations(currentAuth: TenantAuth) {
    const data = await getConversations(currentAuth);
    setConversations(data);
    if (!selectedPhone && data[0]?.phone) setSelectedPhone(data[0].phone);
  }

  useEffect(() => {
    if (!auth) return;
    refreshConversations(auth).catch(console.error);
  }, [auth]);

  useEffect(() => {
    if (!selectedPhone || !auth) return;
    getMessages(selectedPhone, auth).then(setMessages).catch(console.error);

    const source = new EventSource(streamMessagesUrl(selectedPhone, auth));
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data?.event === 'message') {
        setMessages((prev) => [...prev, data.message]);
        refreshConversations(auth).catch(console.error);
      }
    };

    return () => source.close();
  }, [selectedPhone, auth]);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!selectedPhone || !text.trim() || !auth) return;
    await sendMessage(selectedPhone, text, auth);
    setText('');
    await refreshConversations(auth);
  }

  async function onTakeOver() {
    if (!selectedPhone || !auth) return;
    await toggleTakeOver(selectedPhone, auth);
    await refreshConversations(auth);
  }

  function onLogout() {
    localStorage.removeItem(STORAGE_KEY);
    setAuth(null);
    setSession(null);
    setConversations([]);
    setMessages([]);
    setSelectedPhone('');
  }

  if (!auth || !session) {
    return (
      <div className="login-screen">
        <form className="login-card" onSubmit={onLogin}>
          <h2>Login do Tenant</h2>
          <p className="muted">Entre com slug e senha do seu tenant SaaS.</p>
          <input value={slugInput} onChange={(event) => setSlugInput(event.target.value)} placeholder="slug do tenant" />
          <input
            value={passwordInput}
            onChange={(event) => setPasswordInput(event.target.value)}
            placeholder="senha"
            type="password"
          />
          {loginError ? <div className="error-text">{loginError}</div> : null}
          <button type="submit" className="primary">Entrar</button>
        </form>
      </div>
    );
  }

  const statusLabel = selectedConversation?.status === 'human' ? 'Humano' : 'Bot IA';

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <strong>{session.name}</strong>
          <div className="muted">Plano: {session.usage.plan} • Uso: {session.usage.messages_used_month}/{session.usage.max_monthly_messages}</div>
          <button onClick={onLogout}>Sair</button>
        </div>
        {conversations.map((conv) => (
          <div
            key={conv.phone}
            className={`conversation-item ${conv.phone === selectedPhone ? 'active' : ''}`}
            onClick={() => setSelectedPhone(conv.phone)}
          >
            <div className="conversation-title">
              <strong>{conv.name || conv.phone}</strong>
              <span className={`badge ${conv.status === 'human' ? 'human' : ''}`}>{conv.status === 'human' ? 'Humano' : 'Bot'}</span>
            </div>
            <div className="muted">{conv.last_message || 'Sem mensagens ainda'}</div>
          </div>
        ))}
      </aside>

      <section className="chat-area">
        <header className="chat-header">
          <div>
            <strong>{selectedConversation?.name || 'Selecione uma conversa'}</strong>
            <div className="muted">{selectedConversation?.phone} • {statusLabel}</div>
          </div>
          <button onClick={onTakeOver}>
            {selectedConversation?.status === 'human' ? 'Retomar com IA' : 'Assumir atendimento'}
          </button>
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
