import { Conversation, Message } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function getConversations(): Promise<Conversation[]> {
  const res = await fetch(`${API_BASE}/api/conversations`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Falha ao carregar conversas');
  return res.json();
}

export async function getMessages(phone: string): Promise<Message[]> {
  const res = await fetch(`${API_BASE}/api/messages/${phone}`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Falha ao carregar mensagens');
  return res.json();
}

export async function sendMessage(phone: string, message: string) {
  const res = await fetch(`${API_BASE}/api/send-message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, message })
  });
  if (!res.ok) throw new Error('Falha ao enviar mensagem');
  return res.json();
}

export async function toggleTakeOver(phone: string) {
  const res = await fetch(`${API_BASE}/api/take-over/${phone}`, { method: 'POST' });
  if (!res.ok) throw new Error('Falha ao alternar atendimento');
  return res.json();
}

export function streamMessagesUrl(phone: string) {
  return `${API_BASE}/api/stream/messages/${phone}`;
}
