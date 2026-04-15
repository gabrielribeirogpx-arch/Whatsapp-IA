'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

import ChatWindow from './ChatWindow';
import Sidebar from './Sidebar';
import { getConversations, getMessages, sendMessage } from '../lib/api';
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

  useEffect(() => {
    getConversations().then((conversationsResponse: Conversation[]) => {
      const unique = Object.values(
        conversationsResponse.reduce<Record<string, Conversation>>((acc, conversation) => {
          acc[conversation.phone] = conversation;
          return acc;
        }, {})
      );

      setConversations(unique);
    });
  }, []);

  const contacts = useMemo<Contact[]>(
    () =>
      conversations.map((conversation) => ({
        id: String(conversation.id),
        name: conversation.name,
        phone: conversation.phone,
        avatarUrl: conversation.avatar_url,
        lastMessage: conversation.last_message
      })),
    [conversations]
  );

  const selectedContact = useMemo(
    () => contacts.find((contact) => contact.id === selectedContactId),
    [contacts, selectedContactId]
  );

  function onSelectContact(contactId: string) {
    setSelectedContactId(contactId);
    const conversation = conversations.find((item) => String(item.id) === contactId);

    if (!conversation) {
      setMessages([]);
      return;
    }

    getMessages(conversation.phone).then((realMessages: Message[]) => {
      setMessages(realMessages.map(toChatMessage));
    });
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
      await sendMessage(selectedContact.phone, text);
    } catch (error) {
      console.error('Falha ao enviar para backend:', error);
    }
  }

  return (
    <div className="wa-layout">
      <Sidebar contacts={contacts} selectedContactId={selectedContactId} onSelectContact={onSelectContact} />
      <ChatWindow
        contact={selectedContact}
        messages={messages}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSend={onSend}
      />
    </div>
  );
}
