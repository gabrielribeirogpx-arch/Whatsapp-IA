'use client';

import { FormEvent, useMemo, useState } from 'react';

import ChatWindow from './ChatWindow';
import Sidebar from './Sidebar';
import { sendMessageToBackend } from '../lib/api';
import { ChatMessage, Contact } from '../lib/types';

const mockContacts: Contact[] = [
  { id: '1', name: 'Ana Silva', phone: '+55 11 99999-0001', lastMessage: 'Consegue me enviar o orçamento?' },
  { id: '2', name: 'João Souza', phone: '+55 11 99999-0002', lastMessage: 'Obrigado pelo retorno!' },
  { id: '3', name: 'Clínica Vida', phone: '+55 11 99999-0003', lastMessage: 'Quero agendar para amanhã.' }
];

const mockMessages: Record<string, ChatMessage[]> = {
  '1': [
    { id: '1', text: 'Olá, tudo bem?', fromMe: false, time: '09:10' },
    { id: '2', text: 'Oi Ana! Tudo ótimo, como posso ajudar?', fromMe: true, time: '09:11' }
  ],
  '2': [{ id: '3', text: 'Recebi a proposta, perfeito!', fromMe: false, time: '10:02' }],
  '3': [{ id: '4', text: 'Tem horário disponível às 14h?', fromMe: false, time: '11:47' }]
};

export default function ChatShell() {
  const [selectedContactId, setSelectedContactId] = useState(mockContacts[0].id);
  const [chatByContact, setChatByContact] = useState<Record<string, ChatMessage[]>>(mockMessages);
  const [inputValue, setInputValue] = useState('');

  const selectedContact = useMemo(
    () => mockContacts.find((contact) => contact.id === selectedContactId),
    [selectedContactId]
  );

  const selectedMessages = chatByContact[selectedContactId] ?? [];

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

    setChatByContact((current) => ({
      ...current,
      [selectedContact.id]: [...(current[selectedContact.id] ?? []), newMessage]
    }));

    setInputValue('');

    try {
      await sendMessageToBackend({ to: selectedContact.phone, message: text });
    } catch (error) {
      console.error('Falha ao enviar para backend:', error);
    }
  }

  const contacts = useMemo(
    () =>
      mockContacts.map((contact) => {
        const lastMessage = (chatByContact[contact.id] ?? []).at(-1)?.text ?? contact.lastMessage;
        return { ...contact, lastMessage };
      }),
    [chatByContact]
  );

  return (
    <div className="wa-layout">
      <Sidebar contacts={contacts} selectedContactId={selectedContactId} onSelectContact={setSelectedContactId} />
      <ChatWindow
        contact={selectedContact}
        messages={selectedMessages}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSend={onSend}
      />
    </div>
  );
}
