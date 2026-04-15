import { Conversation, Message, SendMessagePayload, TenantAuth, TenantSession } from './types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL;
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'https://SEU_BACKEND_URL';

function tenantHeaders(auth: TenantAuth) {
  return {
    'X-Tenant-Slug': auth.slug,
    'X-Tenant-Password': auth.password
  };
}

export async function tenantLogin(auth: TenantAuth): Promise<TenantSession> {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth)
  });

  if (!res.ok) throw new Error('Falha de autenticação do tenant');
  return res.json();
}

export async function getConversations() {
  const res = await fetch(`${BASE_URL}/api/conversations`);
  return res.json();
}

export async function getMessages(conversationId: string) {
  const res = await fetch(`${BASE_URL}/api/messages/${conversationId}`);
  return res.json();
}

export async function sendMessage(phone: string, message: string, auth: TenantAuth) {
  const res = await fetch(`${BASE_URL}/api/send-message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...tenantHeaders(auth)
    },
    body: JSON.stringify({ phone, message })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function toggleTakeOver(phone: string, auth: TenantAuth) {
  const res = await fetch(`${BASE_URL}/api/take-over/${phone}`, {
    method: 'POST',
    headers: tenantHeaders(auth)
  });
  if (!res.ok) throw new Error('Falha ao alternar atendimento');
  return res.json();
}

export function streamMessagesUrl(phone: string, auth: TenantAuth) {
  const params = new URLSearchParams({
    tenant_slug: auth.slug,
    tenant_password: auth.password
  });
  return `${BASE_URL}/api/stream/messages/${phone}?${params.toString()}`;
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
