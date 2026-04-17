import {
  CRMContact,
  Conversation,
  KnowledgeCrawlPayload,
  KnowledgeCrawlResult,
  KnowledgeItem,
  KnowledgePayload,
  KnowledgeUploadResult,
  Message,
  ConversationMode,
  Product,
  ProductPayload,
  SendMessagePayload,
  TenantSession,
  PipelineStage,
  BotRule,
  BotRulePayload
} from './types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL;
const TENANT_STORAGE_KEY = 'tenant';
const TOKEN_STORAGE_KEY = 'token';
const TENANT_ID_STORAGE_KEY = 'tenant_id';

function buildApiUrl(path: string) {
  if (!BASE_URL) {
    throw new Error('NEXT_PUBLIC_API_URL não está configurado.');
  }

  if (/^https?:\/\//.test(path)) return path;
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

function clearAuthSession() {
  if (typeof window === 'undefined') return;

  localStorage.removeItem(TENANT_STORAGE_KEY);
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  localStorage.removeItem(TENANT_ID_STORAGE_KEY);
}

export function getTenantSessionFromStorage(): TenantSession | null {
  if (typeof window === 'undefined') return null;

  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  const tenantId = localStorage.getItem(TENANT_ID_STORAGE_KEY);
  const saved = localStorage.getItem(TENANT_STORAGE_KEY);

  if (!token || !tenantId) return null;

  if (!saved) {
    return { token, tenant_id: tenantId };
  }

  try {
    const parsed = JSON.parse(saved) as Partial<TenantSession>;
    return {
      token,
      tenant_id: tenantId,
      slug: parsed.slug
    };
  } catch {
    localStorage.removeItem(TENANT_STORAGE_KEY);
    return { token, tenant_id: tenantId };
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const isBrowser = typeof window !== 'undefined';
  const headers = new Headers(init.headers);

  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (isBrowser) {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    const tenantId = localStorage.getItem(TENANT_ID_STORAGE_KEY);

    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    if (tenantId) {
      headers.set('X-Tenant-ID', tenantId);
    }
  }

  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers
  });

  if (response.status === 401 && isBrowser) {
    clearAuthSession();
    window.location.href = '/login';
  }

  return response;
}

async function parseApiResponse<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function registerTenant(name: string, phone_number_id: string): Promise<TenantSession> {
  const res = await apiFetch('/api/register', {
    method: 'POST',
    body: JSON.stringify({ name, phone_number_id })
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }

  return res.json();
}

export async function tenantLogin(phone_number_id: string): Promise<TenantSession> {
  const res = await apiFetch('/api/login', {
    method: 'POST',
    body: JSON.stringify({ phone_number_id })
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }

  return res.json();
}

export async function getConversations(): Promise<Conversation[]> {
  const res = await apiFetch('/api/conversations');
  return parseApiResponse<Conversation[]>(res);
}

export async function getMessagesByConversation(conversationId: string): Promise<Message[]> {
  const res = await apiFetch(`/api/messages/conversation/${conversationId}`);
  return parseApiResponse<Message[]>(res);
}

export async function updateConversationMode(conversationId: string, mode: ConversationMode) {
  const token = localStorage.getItem('token');
  const newMode = mode;
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  if (!API_URL) {
    throw new Error('NEXT_PUBLIC_API_URL não está configurado.');
  }

  console.log('MODE:', newMode);
  console.log('PATCH MODE URL:', `${API_URL}/api/conversations/${conversationId}/mode?mode=${newMode}`);

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/api/conversations/${conversationId}/mode?mode=${newMode}`,
    {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`
      }
    }
  );

  return parseApiResponse(res);
}

export async function sendMessage(phone: string, message: string, contact_id?: string) {
  const res = await apiFetch('/api/send-message', {
    method: 'POST',
    body: JSON.stringify({ phone, message, contact_id })
  });
  return parseApiResponse(res);
}

export async function getContacts(): Promise<CRMContact[]> {
  const res = await apiFetch('/api/contacts');
  return parseApiResponse<CRMContact[]>(res);
}

export async function sendMessageToBackend(payload: SendMessagePayload) {
  const response = await apiFetch('/api/send-message', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error('Não foi possível enviar mensagem para o backend.');
  }

  return response.json();
}

export async function getProducts(): Promise<Product[]> {
  const res = await apiFetch('/api/products');
  return parseApiResponse<Product[]>(res);
}

export async function createProduct(payload: ProductPayload): Promise<Product> {
  const res = await apiFetch('/api/products', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<Product>(res);
}

export async function updateProduct(productId: string, payload: ProductPayload): Promise<Product> {
  const res = await apiFetch(`/api/products/${productId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<Product>(res);
}

export async function deleteProduct(productId: string): Promise<void> {
  const res = await apiFetch(`/api/products/${productId}`, {
    method: 'DELETE'
  });

  if (!res.ok) throw new Error(await res.text());
}

export async function getKnowledge(): Promise<KnowledgeItem[]> {
  const res = await apiFetch('/api/knowledge');
  return parseApiResponse<KnowledgeItem[]>(res);
}

export async function createKnowledge(payload: KnowledgePayload): Promise<KnowledgeItem> {
  const res = await apiFetch('/api/knowledge', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<KnowledgeItem>(res);
}

export async function deleteKnowledge(knowledgeId: string): Promise<void> {
  const res = await apiFetch(`/api/knowledge/${knowledgeId}`, {
    method: 'DELETE'
  });

  if (!res.ok) throw new Error(await res.text());
}

export async function uploadKnowledgePdf(file: File): Promise<KnowledgeUploadResult> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await apiFetch('/api/knowledge/upload-pdf', {
    method: 'POST',
    body: formData
  });

  return parseApiResponse<KnowledgeUploadResult>(res);
}

export async function crawlKnowledgeSite(payload: KnowledgeCrawlPayload): Promise<KnowledgeCrawlResult> {
  const res = await apiFetch('/api/knowledge/crawl', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<KnowledgeCrawlResult>(res);
}

export async function getPipeline(): Promise<PipelineStage[]> {
  const res = await apiFetch('/api/pipeline');
  return parseApiResponse<PipelineStage[]>(res);
}

export async function moveLeadToStage(leadId: string, stageId: string) {
  const res = await apiFetch(`/api/leads/${leadId}/move`, {
    method: 'POST',
    body: JSON.stringify({ stage_id: stageId })
  });

  return parseApiResponse(res);
}


export async function getBotRules(): Promise<BotRule[]> {
  const res = await apiFetch('/api/bot/rules');
  return parseApiResponse<BotRule[]>(res);
}

export async function createBotRule(payload: BotRulePayload): Promise<BotRule> {
  const res = await apiFetch('/api/bot/rules', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<BotRule>(res);
}

export async function deleteBotRule(ruleId: string): Promise<void> {
  const res = await apiFetch(`/api/bot/rules/${ruleId}`, {
    method: 'DELETE'
  });

  if (!res.ok) throw new Error(await res.text());
}
