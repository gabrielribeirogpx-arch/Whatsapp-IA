'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import ChatWindow from './chat-window';
import Sidebar from './sidebar';
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
  const [selectedPhone, setSelectedPhone] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [messageText, setMessageText] = useState('');

  const selectedConversation = useMemo(
    () => conversations.find((conversation) => conversation.phone === selectedPhone),
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

  const refreshConversations = useCallback(async (currentAuth: TenantAuth) => {
    const data = await getConversations(currentAuth);
    setConversations(data);

    setSelectedPhone((currentSelectedPhone) => {
      if (currentSelectedPhone) return currentSelectedPhone;
      return data[0]?.phone ?? '';
    });
  }, []);

  useEffect(() => {
    if (!auth) return;
    refreshConversations(auth).catch(console.error);
  }, [auth, refreshConversations]);

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
  }, [selectedPhone, auth, refreshConversations]);

  async function onLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextAuth = {
      slug: slugInput.trim(),
      password: passwordInput.trim()
    };

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

  async function onSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPhone || !messageText.trim() || !auth) return;

    await sendMessage(selectedPhone, messageText.trim(), auth);
    setMessageText('');
    await refreshConversations(auth);
  }

  async function onToggleTakeOver() {
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
          <h1>WhatsApp IA</h1>
          <p>Faça login com o slug e senha do tenant para acessar o atendimento.</p>

          <label htmlFor="slug">Tenant slug</label>
          <input
            id="slug"
            value={slugInput}
            onChange={(event) => setSlugInput(event.target.value)}
            placeholder="slug do tenant"
            required
          />

          <label htmlFor="password">Senha</label>
          <input
            id="password"
            value={passwordInput}
            onChange={(event) => setPasswordInput(event.target.value)}
            placeholder="senha"
            type="password"
            required
          />

          {loginError ? <p className="error-text">{loginError}</p> : null}

          <button type="submit" className="primary-button">
            Entrar
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="chat-layout">
      <Sidebar
        session={session}
        conversations={conversations}
        selectedPhone={selectedPhone}
        onSelectConversation={setSelectedPhone}
        onLogout={onLogout}
      />

      <ChatWindow
        selectedConversation={selectedConversation}
        messages={messages}
        messageText={messageText}
        onMessageTextChange={setMessageText}
        onSendMessage={onSendMessage}
        onToggleTakeOver={onToggleTakeOver}
      />
    </div>
  );
}
