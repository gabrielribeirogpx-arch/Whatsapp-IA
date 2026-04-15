'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import ChatWindow from './ChatWindow';
import Sidebar from './Sidebar';
import { getConversations, getMessages, getMessagesByContact, sendMessage } from '../lib/api';
import { ChatMessage, Contact, Conversation, Message } from '../lib/types';

function toChatMessage(message: Message): ChatMessage {
  const parsedDate = new Date(message.timestamp);
  const time = Number.isNaN(parsedDate.getTime())
    ? '--:--'
    : parsedDate.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

  return {
    id: String(message.id),
    text: message.content,
    fromMe: message.from_me,
    time
  };
}

export default function ChatShell() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedContactId, setSelectedContactId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const fetchConversations = useCallback(async () => {
    const conversationsResponse = await getConversations();
    const unique = Object.values(
      conversationsResponse.reduce<Record<string, Conversation>>((acc, conversation) => {
        acc[conversation.phone] = conversation;
        return acc;
      }, {})
    );

    setConversations(unique);
    if (unique.length && !selectedContactId) {
      setSelectedContactId(String(unique[0].contact_id ?? unique[0].id));
    }
  }, [selectedContactId]);

  const fetchMessages = useCallback(
    async (conversationId: string) => {
      const conversation = conversations.find((item) => String(item.contact_id ?? item.id) === conversationId);

      if (!conversation) {
        setMessages([]);
        return;
      }

      const loadMessages = conversation.contact_id
        ? getMessagesByContact(conversation.contact_id)
        : getMessages(conversation.phone);

      const realMessages: Message[] = await loadMessages;
      setMessages(realMessages.map(toChatMessage));
    },
    [conversations]
  );

  useEffect(() => {
    fetchConversations().catch(() => undefined);
  }, [fetchConversations]);

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
          status: conversation.status
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

  useEffect(() => {
    if (!selectedContactId) return;

    fetchMessages(selectedContactId).catch(() => undefined);
  }, [selectedContactId, fetchMessages]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchConversations().catch(() => undefined);
      if (selectedContactId) {
        fetchMessages(selectedContactId).catch(() => undefined);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [selectedContactId, fetchConversations, fetchMessages]);

  function onSelectContact(contactId: string) {
    setSelectedContactId(contactId);
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
      />
    </div>
  );
}
