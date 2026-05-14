'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import ChatWindow from './ChatWindow';
import Sidebar from './Sidebar';
import CRMContactSidebar from './inbox/CRMContactSidebar';
import { getConversations, getMessagesByConversation, sendMessage, updateConversationMode } from '../lib/api';
import { ChatMessage, Contact, Conversation, ConversationMode, Message } from '../lib/types';

function toChatMessage(message: Message): ChatMessage {
  const parsedDate = new Date(message.created_at);
  const time = Number.isNaN(parsedDate.getTime())
    ? '--:--'
    : parsedDate.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

  return {
    id: String(message.id),
    text: message.content,
    fromMe: message.role === 'assistant',
    time,
    createdAt: message.created_at,
    status: message.role === 'assistant' ? 'read' : 'delivered',
    isNew: Date.now() - parsedDate.getTime() < 8000
  };
}

export default function ChatShell() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedContactId, setSelectedContactId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState<ConversationMode>('human');
  const [modeUpdating, setModeUpdating] = useState(false);
  const [modeNotice, setModeNotice] = useState('');
  const [modeError, setModeError] = useState('');
  const [querySelectionMissing, setQuerySelectionMissing] = useState(false);
  const [crmOpen, setCrmOpen] = useState(false);


  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      router.replace('/login');
    }
  }, [router]);


  const fetchMessages = useCallback(
    async (conversationId: string) => {
      const conversation = conversations.find((item) => String(item.contact_id ?? item.id) === conversationId);

      if (!conversation) {
        setMessages([]);
        return;
      }

      const realMessages: Message[] = await getMessagesByConversation(String(conversation.id));
      setMessages(realMessages.map(toChatMessage));
    },
    [conversations]
  );


  const contacts = useMemo<Contact[]>(
    () =>
      conversations.map((conversation) => {
        const updatedAt = conversation.updated_at ? new Date(conversation.updated_at) : null;
        const now = Date.now();
        const elapsed = updatedAt ? now - updatedAt.getTime() : Number.POSITIVE_INFINITY;
        const isOnline = elapsed <= 2 * 60 * 1000;
        const isTyping = elapsed <= 20 * 1000;

        return {
          id: String(conversation.contact_id ?? conversation.id),
          name: conversation.name,
          phone: conversation.phone,
          avatarUrl: conversation.avatar_url,
          stage: conversation.stage,
          score: conversation.score,
          lastMessage: conversation.last_message,
          lastMessageAt: conversation.updated_at,
          isOnline,
          isTyping,
          status: conversation.mode
        };
      }),
    [conversations]
  );

  const orderedContacts = useMemo(() => {
    const getPriority = (status?: string) => {
      const normalizedStatus = status?.toLowerCase();

      if (normalizedStatus === 'human') return 2;
      if (normalizedStatus === 'bot' || normalizedStatus === 'ai') return 1;
      return 0;
    };

    return [...contacts].sort((a, b) => {
      const priorityDiff = getPriority(a.status) - getPriority(b.status);
      if (priorityDiff !== 0) return priorityDiff;

      const dateA = a.lastMessageAt ? new Date(a.lastMessageAt).getTime() : 0;
      const dateB = b.lastMessageAt ? new Date(b.lastMessageAt).getTime() : 0;
      return dateB - dateA;
    });
  }, [contacts]);

  const unansweredCount = useMemo(
    () =>
      orderedContacts.filter((contact) => {
        const normalizedStatus = contact.status?.toLowerCase();
        return normalizedStatus !== 'human' && normalizedStatus !== 'bot' && normalizedStatus !== 'ai';
      }).length,
    [orderedContacts]
  );

  const selectedContact = useMemo(
    () => contacts.find((contact) => contact.id === selectedContactId),
    [contacts, selectedContactId]
  );
  const selectedConversation = useMemo(
    () => conversations.find((item) => String(item.contact_id ?? item.id) === selectedContactId),
    [conversations, selectedContactId]
  );

  useEffect(() => {
    if (!selectedConversation) {
      return;
    }

    const currentMode = selectedConversation.mode?.toLowerCase();
    if (currentMode === 'bot' || currentMode === 'ai' || currentMode === 'human') {
      setMode(currentMode);
      return;
    }
  }, [selectedConversation]);

  useEffect(() => {
    if (!modeNotice && !modeError) return;

    const timeoutId = window.setTimeout(() => {
      setModeNotice('');
      setModeError('');
    }, 2200);

    return () => window.clearTimeout(timeoutId);
  }, [modeNotice, modeError]);

  useEffect(() => {
    if (!selectedContactId) return;

    fetchMessages(selectedContactId).catch(() => undefined);
    if (typeof window !== 'undefined' && window.innerWidth > 1200) {
      setCrmOpen(true);
    }
  }, [selectedContactId, fetchMessages]);

  useEffect(() => {
    if (!selectedContactId) return;
    if (typeof window === 'undefined') return;

    const tenantId = localStorage.getItem('tenant_id');
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!selectedConversation || !tenantId || !apiUrl) return;

    const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl;
    const eventSource = new EventSource(
      `${baseUrl}/api/sse/messages/${selectedConversation.id}?tenant_id=${encodeURIComponent(tenantId)}`
    );

    eventSource.onmessage = () => {
      fetchMessages(selectedContactId).catch(() => undefined);
      getConversations().then(setConversations).catch(() => undefined);
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [selectedContactId, selectedConversation, fetchMessages]);


  useEffect(() => {
    getConversations()
      .then((items) => {
        const targetContactId = searchParams.get('contact_id');
        const targetPhone = searchParams.get('phone');
        const normalizedTargetPhone = targetPhone ? targetPhone.replace(/\D/g, '') : '';

        setConversations(items);

        const matchedConversation = items.find((conversation) => {
          const byContactId = targetContactId
            ? String(conversation.contact_id ?? conversation.id) === targetContactId
            : false;

          const byPhone = normalizedTargetPhone
            ? conversation.phone.replace(/\D/g, '') === normalizedTargetPhone
            : false;

          return byContactId || byPhone;
        });

        if (matchedConversation) {
          setQuerySelectionMissing(false);
          setSelectedContactId(String(matchedConversation.contact_id ?? matchedConversation.id));
          return;
        }

        if (targetContactId || targetPhone) {
          setQuerySelectionMissing(true);
        }

        setSelectedContactId((current) => current || (items[0] ? String(items[0].contact_id ?? items[0].id) : ''));
      })
      .catch(() => setConversations([]));
  }, [searchParams]);


  function onSelectContact(contactId: string) {
    setSelectedContactId(contactId);
    setCrmOpen(true);
  }

  async function onSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedContact || !inputValue.trim()) return;

    const text = inputValue.trim();
    const now = new Date();
    const newMessage: ChatMessage = {
      id: `${now.getTime()}`,
      text,
      fromMe: true,
      time: now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((current) => [...current, newMessage]);
    setInputValue('');

    try {
      await sendMessage(selectedContact.phone, text, selectedContact.id);
    } catch (error) {
      console.error('Falha ao enviar para backend:', error);
    }
  }

  async function handleChangeMode(newMode: ConversationMode) {
    if (!selectedConversation || modeUpdating || newMode === mode) return;

    const conversationId = String(selectedConversation.id);
    const previousMode = mode;

    setModeError('');
    setModeNotice('');
    setModeUpdating(true);

    try {
      await updateConversationMode(conversationId, newMode);

      setMode(newMode);
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === selectedConversation.id ? { ...conversation, mode: newMode } : conversation
        )
      );
      setModeNotice('Modo atualizado.');
    } catch (err) {
      console.error('Erro ao atualizar modo:', err);
      setMode(previousMode);
      setModeError('Não foi possível atualizar o modo.');
    } finally {
      setModeUpdating(false);
    }
  }

  return (
    <div className="wa-layout">
      <Sidebar
        contacts={orderedContacts}
        selectedContactId={selectedContactId}
        onSelectContact={onSelectContact}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        unansweredCount={unansweredCount}
      />
      <ChatWindow
        contact={selectedContact}
        messages={messages}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSend={onSend}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        mode={mode}
        modeUpdating={modeUpdating}
        modeNotice={modeNotice}
        modeError={modeError}
        emptyStateMessage={querySelectionMissing ? 'Conversa ainda não encontrada para este contato.' : undefined}
        onModeChange={handleChangeMode}
      />
      <CRMContactSidebar contact={selectedContact} open={crmOpen} onClose={() => setCrmOpen(false)} />
    </div>
  );
}
