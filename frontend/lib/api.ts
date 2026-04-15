import {
  CRMContact,
  Conversation,
  KnowledgeCrawlPayload,
  KnowledgeCrawlResult,
  KnowledgeItem,
  KnowledgePayload,
  KnowledgeUploadResult,
  Message,
  Product,
  ProductPayload,
  SendMessagePayload,
  TenantSession,
  PipelineStage
} from './types';

const API_PREFIX = '/api';
const TENANT_STORAGE_KEY = 'tenant';
const TENANT_ID_STORAGE_KEY = 'tenant_id';

export function getTenantSessionFromStorage(): TenantSession | null {
  if (typeof window === 'undefined') return null;

  const saved = localStorage.getItem(TENANT_STORAGE_KEY);
  if (!saved) return null;

  try {
    const parsed = JSON.parse(saved) as TenantSession;
    if (parsed?.tenant_id) return parsed;

    const tenantId = localStorage.getItem(TENANT_ID_STORAGE_KEY);
    if (!tenantId || !parsed?.slug) return null;

    return { ...parsed, tenant_id: tenantId };
  } catch {
    localStorage.removeItem(TENANT_STORAGE_KEY);
    localStorage.removeItem(TENANT_ID_STORAGE_KEY);
    return null;
  }
}

function tenantHeaders() {
  const tenant = getTenantSessionFromStorage();
  console.log('TENANT_ID:', tenant?.tenant_id ?? null);
  return {
    'Content-Type': 'application/json',
    'x-tenant-slug': tenant?.slug ?? '',
    'x-tenant-id': tenant?.tenant_id ?? ''
  };
}

function tenantAuthHeaders() {
  const tenant = getTenantSessionFromStorage();
  return {
    'x-tenant-slug': tenant?.slug ?? '',
    'x-tenant-id': tenant?.tenant_id ?? ''
  };
}

export async function registerTenant(name: string, phone_number_id: string): Promise<TenantSession> {
  const res = await fetch(`${API_PREFIX}/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, phone_number_id })
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return res.json();
}

export async function tenantLogin(phone_number_id: string): Promise<TenantSession> {
  const res = await fetch(`${API_PREFIX}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone_number_id })
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return res.json();
}

export async function getConversations(): Promise<Conversation[]> {
  const res = await fetch(`${API_PREFIX}/conversations`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  console.log('CONVERSAS:', data);

  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.conversations)) return data.conversations;
  return [];
}

export async function getMessages(phone: string): Promise<Message[]> {
  const res = await fetch(`${API_PREFIX}/messages/${phone}`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMessagesByContact(contactId: string): Promise<Message[]> {
  const res = await fetch(`${API_PREFIX}/messages/by-contact/${contactId}`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendMessage(phone: string, message: string, contact_id?: string) {
  const res = await fetch(`${API_PREFIX}/send-message`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify({ phone, message, contact_id })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getContacts(): Promise<CRMContact[]> {
  const res = await fetch(`${API_PREFIX}/contacts`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendMessageToBackend(payload: SendMessagePayload) {
  const response = await fetch(`${API_PREFIX}/send-message`, {
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


export async function getProducts(): Promise<Product[]> {
  const res = await fetch(`${API_PREFIX}/products`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createProduct(payload: ProductPayload): Promise<Product> {
  const res = await fetch(`${API_PREFIX}/products`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify(payload)
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProduct(productId: string, payload: ProductPayload): Promise<Product> {
  const res = await fetch(`${API_PREFIX}/products/${productId}`, {
    method: 'PUT',
    headers: tenantHeaders(),
    body: JSON.stringify(payload)
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteProduct(productId: string): Promise<void> {
  const res = await fetch(`${API_PREFIX}/products/${productId}`, {
    method: 'DELETE',
    headers: tenantHeaders()
  });

  if (!res.ok) throw new Error(await res.text());
}

export async function getKnowledge(): Promise<KnowledgeItem[]> {
  const res = await fetch(`${API_PREFIX}/knowledge`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createKnowledge(payload: KnowledgePayload): Promise<KnowledgeItem> {
  const res = await fetch(`${API_PREFIX}/knowledge`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify(payload)
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteKnowledge(knowledgeId: string): Promise<void> {
  const res = await fetch(`${API_PREFIX}/knowledge/${knowledgeId}`, {
    method: 'DELETE',
    headers: tenantHeaders()
  });

  if (!res.ok) throw new Error(await res.text());
}

export async function uploadKnowledgePdf(file: File): Promise<KnowledgeUploadResult> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_PREFIX}/knowledge/upload-pdf`, {
    method: 'POST',
    headers: tenantAuthHeaders(),
    body: formData
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}


export async function crawlKnowledgeSite(payload: KnowledgeCrawlPayload): Promise<KnowledgeCrawlResult> {
  const res = await fetch(`${API_PREFIX}/knowledge/crawl`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify(payload)
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPipeline(): Promise<PipelineStage[]> {
  const res = await fetch(`${API_PREFIX}/pipeline`, { headers: tenantHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function moveLeadToStage(leadId: string, stageId: string) {
  const res = await fetch(`${API_PREFIX}/leads/${leadId}/move`, {
    method: 'POST',
    headers: tenantHeaders(),
    body: JSON.stringify({ stage_id: stageId })
  });

  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
