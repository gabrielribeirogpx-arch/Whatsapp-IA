import { Conversation, Message, TenantAuth, TenantSession } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function tenantHeaders(auth: TenantAuth) {
  return {
    'X-Tenant-Slug': auth.slug,
    'X-Tenant-Password': auth.password
  };
}

export async function tenantLogin(auth: TenantAuth): Promise<TenantSession> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(auth)
  });

  if (!res.ok) throw new Error('Falha de autenticação do tenant');
  return res.json();
}

export async function getConversations(auth: TenantAuth): Promise<Conversation[]> {
  const res = await fetch(`${API_BASE}/api/conversations`, {
    cache: 'no-store',
    headers: tenantHeaders(auth)
  });
  if (!res.ok) throw new Error('Falha ao carregar conversas');
  return res.json();
}

export async function getMessages(phone: string, auth: TenantAuth): Promise<Message[]> {
  const res = await fetch(`${API_BASE}/api/messages/${phone}`, {
    cache: 'no-store',
    headers: tenantHeaders(auth)
  });
  if (!res.ok) throw new Error('Falha ao carregar mensagens');
  return res.json();
}

export async function sendMessage(phone: string, message: string, auth: TenantAuth) {
  const res = await fetch(`${API_BASE}/api/send-message`, {
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
  const res = await fetch(`${API_BASE}/api/take-over/${phone}`, {
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
  return `${API_BASE}/api/stream/messages/${phone}?${params.toString()}`;
}
