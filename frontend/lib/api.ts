import { Conversation, Message, SendMessagePayload, TenantSession } from './types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL;
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'https://SEU_BACKEND_URL';
const TENANT_STORAGE_KEY = 'tenant';

export function getTenantSessionFromStorage(): TenantSession | null {
  if (typeof window === 'undefined') return null;

  const saved = localStorage.getItem(TENANT_STORAGE_KEY);
  if (!saved) return null;

  try {
    return JSON.parse(saved) as TenantSession;
  } catch {
    localStorage.removeItem(TENANT_STORAGE_KEY);
    return null;
  }
}

function tenantHeaders() {
  const tenant = getTenantSessionFromStorage();
  return {
    'Content-Type': 'application/json',
    'x-tenant-slug': tenant?.slug ?? ''
  };
}

export async function registerTenant(name: string, phone_number_id: string): Promise<TenantSession> {
  const res = await fetch(`${BASE_URL}/api/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, phone_number_id })
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function tenantLogin(slug: string): Promise<TenantSession> {
  const res = await fetch(`${BASE_URL}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug })
  });

  if (!res.ok) throw new Error('Falha de autenticação do tenant');
  return res.json();
}

export async function getConversations() {
  const res = await fetch(`${BASE_URL}/api/conversations`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMessages(phone: string) {
  const res = await fetch(`${BASE_URL}/api/messages/${phone}`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendMessage(phone: string, message: string) {
  const res = await fetch(`${BASE_URL}/api/send-message`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify({ phone, message })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendMessageToBackend(payload: SendMessagePayload) {
  const response = await fetch(`${BACKEND_URL}/send-message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error('Não foi possível enviar mensagem para o backend.');
  }

  return response.json();
}
