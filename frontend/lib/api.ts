import type {
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
  PipelineStagePayload,
  BotRule,
  BotRulePayload,
  FlowGraphPayload,
  FlowNodePayload,
  FlowEdgePayload,
  FlowItem,
  FlowPayload,
  FlowVersionItem,
  FlowAnalytics,
  SystemSettings,
  SystemSettingsPayload,
  DeleteFlowResponse,
  WhatsAppProvider,
  WhatsAppTemplate,
  WhatsAppCampaign,
  WhatsAppCampaignRecipient,
  AccountMe,
  AccountProfile,
  AccountPreferences,
  AccountSecurity,
  AuditLog,
  WorkspaceUser,
  TaskItem,
  TaskUpdatePayload,
  GoogleCalendarConnectionStatus
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const TENANT_STORAGE_KEY = 'tenant';
const TOKEN_STORAGE_KEY = 'token';
const TENANT_ID_STORAGE_KEY = 'tenant_id';

function getTenantFromSubdomain(hostname: string): string | null {
  const normalized = hostname.split(':')[0].trim().toLowerCase();
  if (!normalized) return null;
  const parts = normalized.split('.');
  if (parts.length < 3) return null;

  const subdomain = parts[0]?.trim();
  if (!subdomain || subdomain === 'www') return null;
  return subdomain;
}

export function getTenantSlugOrId(): string | null {
  if (typeof window === 'undefined') return null;

  const storedTenant = localStorage.getItem(TENANT_STORAGE_KEY);
  if (storedTenant) {
    try {
      const parsed = JSON.parse(storedTenant) as Partial<TenantSession>;
      if (parsed.slug) return parsed.slug;
      if (parsed.tenant_id) return parsed.tenant_id;
    } catch {
      if (storedTenant.trim()) return storedTenant.trim();
    }
  }

  return localStorage.getItem(TENANT_ID_STORAGE_KEY) || getTenantFromSubdomain(window.location.hostname);
}

export function getTenant(): string | null {
  if (typeof window === 'undefined') return null;

  const tenantId = localStorage.getItem(TENANT_ID_STORAGE_KEY);
  if (tenantId) return tenantId;

  const storedTenant = localStorage.getItem(TENANT_STORAGE_KEY);
  if (storedTenant) {
    try {
      const parsed = JSON.parse(storedTenant) as Partial<TenantSession>;
      if (parsed.tenant_id) return parsed.tenant_id;
      if (parsed.slug) return parsed.slug;
    } catch {
      if (storedTenant.trim()) return storedTenant.trim();
    }
  }

  return getTenantFromSubdomain(window.location.hostname);
}

function buildApiUrl(path: string) {
  if (!API_URL) {
    throw new Error('NEXT_PUBLIC_API_URL não está configurado.');
  }

  if (/^https?:\/\//.test(path)) return path;
  return `${API_URL}${path.startsWith('/') ? path : `/${path}`}`;
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

/**
 * Wrapper padrão para requisições HTTP no frontend.
 *
 * Mantém a injeção automática de `Content-Type` (quando aplicável) e `X-Tenant-ID`
 * para rotas protegidas. Rotas de flow (`/api/flows*`) devem usar somente este
 * wrapper para garantir consistência de autenticação e tenancy.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const isBrowser = typeof window !== 'undefined';
  const headers = new Headers(init.headers);
  const hasBody = typeof init.body !== 'undefined' && init.body !== null;

  if (hasBody && !headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const resolvedPath = (() => {
    if (!/^https?:\/\//.test(path)) return path;

    try {
      return new URL(path).pathname;
    } catch {
      return path;
    }
  })();

  if (isBrowser) {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    const tenantId = getTenant();

    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    const isProtectedApiRoute =
      resolvedPath.startsWith('/api') && !resolvedPath.startsWith('/api/login') && !resolvedPath.startsWith('/api/register');

    if (tenantId && isProtectedApiRoute && !headers.has('X-Tenant-ID')) {
      headers.set('X-Tenant-ID', tenantId);
    } else if (isProtectedApiRoute && resolvedPath.startsWith('/api/flows')) {
      throw new Error('Tenant não encontrado para requisições de flow.');
    }
  }

  const url = buildApiUrl(path);
  console.log('API CALL →', url);

  const response = await fetch(url, {
    ...init,
    headers
  });

  if (response.status === 401 && isBrowser) {
    clearAuthSession();
    window.location.href = '/login';
  }

  return response;
}

export async function parseApiResponse<T>(res: Response): Promise<T> {
  const body = await res.text();

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${body}`);
  }

  if (res.status === 204 || res.status === 205 || body.trim().length === 0) {
    return undefined as T;
  }

  return JSON.parse(body) as T;
}

export async function registerTenant(payload: Record<string, string>, turnstileToken: string): Promise<TenantSession> {
  const requestPayload = { ...payload, turnstile_token: turnstileToken };
  const sanitizedPayload = {
    ...requestPayload,
    password: payload.password ? '***' : payload.password,
    confirm_password: payload.confirm_password ? '***' : payload.confirm_password,
    turnstile_token: turnstileToken ? '***' : turnstileToken
  };
  console.log('[REGISTER REQUEST]', sanitizedPayload);

  const res = await apiFetch('/api/register', {
    method: 'POST',
    body: JSON.stringify(requestPayload)
  });

  return parseApiResponse<TenantSession>(res);
}

export async function tenantLogin(email: string, password: string, turnstileToken: string): Promise<TenantSession> {
  const res = await apiFetch('/api/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, turnstile_token: turnstileToken })
  });

  return parseApiResponse<TenantSession>(res);
}


export async function resetConversation(conversationId: string): Promise<{ ok: boolean }> {
  const res = await apiFetch(`/api/admin/reset-conversation/${conversationId}`, {
    method: 'POST'
  });

  return parseApiResponse<{ ok: boolean }>(res);
}

export async function getConversations(limit?: number): Promise<Conversation[]> {
  const query = typeof limit === 'number' && Number.isFinite(limit) ? `?limit=${Math.max(1, Math.floor(limit))}` : '';
  const res = await apiFetch(`/api/conversations${query}`);
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

  console.log('TOKEN:', token);
  console.log('MODE:', newMode);
  console.log('PATCH MODE URL:', `${API_URL}/api/conversations/${conversationId}/mode?mode=${newMode}`);

  const res = await apiFetch(`/api/conversations/${conversationId}/mode?mode=${newMode}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`
    }
  });

  return parseApiResponse(res);
}

export type ConversationAssignmentResponse = {
  phone: string;
  status: string;
  conversation_id?: string | null;
  mode?: string | null;
  assigned_user_id?: string | null;
  assigned_user_name?: string | null;
  conversation?: Conversation | null;
};

export async function assignConversationToSelf(conversationId: string): Promise<ConversationAssignmentResponse> {
  const res = await apiFetch(`/api/conversations/${conversationId}/assign`, {
    method: 'PATCH',
    body: JSON.stringify({ self: true })
  });
  return parseApiResponse<ConversationAssignmentResponse>(res);
}

export async function releaseConversationAssignment(conversationId: string): Promise<ConversationAssignmentResponse> {
  const res = await apiFetch(`/api/conversations/${conversationId}/assign`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: null })
  });
  return parseApiResponse<ConversationAssignmentResponse>(res);
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
  const payload = await parseApiResponse<CRMContact[] | { items?: CRMContact[]; contacts?: CRMContact[] }>(res);
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload.items)) return payload.items;
  if (Array.isArray(payload.contacts)) return payload.contacts;
  return [];
}

export async function sendMessageToBackend(payload: SendMessagePayload) {
  const response = await apiFetch('/api/send-message', {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse(response);
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

  await parseApiResponse<void>(res);
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

  await parseApiResponse<void>(res);
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


export type DashboardActivity = {
  id: string;
  type: string;
  title: string;
  description?: string | null;
  entity_type?: string | null;
  contact_name?: string | null;
  phone?: string | null;
  entity_id?: string | null;
  created_at: string;
};

export async function getDashboardActivity(): Promise<DashboardActivity[]> {
  const res = await apiFetch('/api/dashboard/activity');
  return parseApiResponse<DashboardActivity[]>(res);
}

export async function getPipeline(): Promise<PipelineStage[]> {
  const res = await apiFetch('/api/pipeline');
  return parseApiResponse<PipelineStage[]>(res);
}

export async function listPipelineStages(): Promise<PipelineStage[]> {
  const res = await apiFetch('/api/pipeline/stages');
  return parseApiResponse<PipelineStage[]>(res);
}

export async function createPipelineStage(payload: Required<Pick<PipelineStagePayload, 'name'>> & Pick<PipelineStagePayload, 'position'>): Promise<PipelineStage> {
  const res = await apiFetch('/api/pipeline', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return parseApiResponse<PipelineStage>(res);
}

export async function updatePipelineStage(stageId: string, payload: PipelineStagePayload): Promise<PipelineStage> {
  const res = await apiFetch(`/api/pipeline/${stageId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
  return parseApiResponse<PipelineStage>(res);
}

export async function reorderPipelineStages(stageIds: string[]): Promise<PipelineStage[]> {
  const res = await apiFetch('/api/pipeline/reorder', {
    method: 'PATCH',
    body: JSON.stringify({ stage_ids: stageIds })
  });
  return parseApiResponse<PipelineStage[]>(res);
}

export async function moveLeadToStage(leadId: string, stageId: string) {
  const normalizedStageId = stageId?.trim();
  if (!normalizedStageId) {
    throw new Error('Etapa de destino ausente para mover lead.');
  }

  const res = await apiFetch(`/api/leads/${leadId}/move`, {
    method: 'PATCH',
    body: JSON.stringify({ stage_id: normalizedStageId })
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

  await parseApiResponse<void>(res);
}


export async function getFlowGraph(tenantId: string, flowId?: string): Promise<FlowGraphPayload> {
  const query = flowId ? `?flow_id=${encodeURIComponent(flowId)}` : '';
  const res = await apiFetch(`/api/flows/${tenantId}${query}`);
  return parseApiResponse<FlowGraphPayload>(res);
}

export async function saveFlowGraph(
  tenantId: string,
  payload: { nodes: FlowNodePayload[]; edges: FlowEdgePayload[] },
  flowId?: string
): Promise<FlowGraphPayload> {
  const query = flowId ? `?flow_id=${encodeURIComponent(flowId)}` : '';
  const res = await apiFetch(`/api/flows/${tenantId}${query}`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseApiResponse<FlowGraphPayload>(res);
}

export async function listFlows(): Promise<FlowItem[]> {
  const res = await apiFetch('/api/flows');
  return parseApiResponse<FlowItem[]>(res);
}

type CreateFlowDebugInfo = {
  url: string;
  status: number;
  body: unknown;
  rawBody: string;
};

export async function createFlow(
  payload: FlowPayload,
  onDebug?: (info: CreateFlowDebugInfo) => void
): Promise<FlowItem> {
  const endpoint = '/api/flows';
  const res = await apiFetch(endpoint, {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  const rawBody = await res.text();
  let body: unknown = null;
  if (rawBody) {
    try {
      body = JSON.parse(rawBody);
    } catch {
      body = rawBody;
    }
  }

  const debugInfo = {
    url: res.url || buildApiUrl(endpoint),
    status: res.status,
    body,
    rawBody
  };

  console.info('[FLOW CREATE API CLIENT]', {
    url: debugInfo.url,
    status: debugInfo.status,
    json: debugInfo.body
  });
  onDebug?.(debugInfo);

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${rawBody}`);
  }

  if (res.status === 204) {
    return undefined as FlowItem;
  }

  return body as FlowItem;
}

export type UpdateFlowApiResult = { ok: boolean; status: number; data: FlowItem | null };

export async function updateFlow(
  flowId: string,
  payload: Pick<FlowPayload, 'name' | 'description' | 'trigger_type' | 'trigger_value'>
): Promise<UpdateFlowApiResult> {
  const endpoint = `/api/flows/${flowId}`;
  console.info('[FLOW EDIT REQUEST URL]', endpoint);
  console.info('[FLOW EDIT SAVE PAYLOAD]', payload);

  const res = await apiFetch(endpoint, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });

  console.info('[FLOW EDIT RESPONSE STATUS]', res.status);
  const bodyText = await res.text();
  console.info('[FLOW EDIT RESPONSE BODY]', bodyText);

  let bodyJson: FlowItem | null = null;
  if (bodyText) {
    try {
      bodyJson = JSON.parse(bodyText) as FlowItem;
    } catch {
      bodyJson = null;
    }
  }

  return { ok: res.ok, status: res.status, data: bodyJson };
}

export async function updateFlowStatus(flowId: string, isActive: boolean): Promise<FlowItem> {
  const res = await apiFetch(`/api/flows/${flowId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  });
  return parseApiResponse<FlowItem>(res);
}

export async function deleteFlow(flowId: string): Promise<DeleteFlowResponse> {
  const res = await apiFetch(`/api/flows/${flowId}`, {
    method: 'DELETE'
  });

  return parseApiResponse<DeleteFlowResponse>(res);
}

export async function duplicateFlow(flowId: string): Promise<FlowItem> {
  const res = await apiFetch(`/api/flows/${flowId}/duplicate`, {
    method: 'POST'
  });
  return parseApiResponse<FlowItem>(res);
}

export async function listFlowVersions(flowId: string): Promise<FlowVersionItem[]> {
  const res = await apiFetch(`/api/flows/${flowId}/versions`);
  return parseApiResponse<FlowVersionItem[]>(res);
}

export async function restoreFlowVersion(flowId: string, versionId: string): Promise<FlowItem> {
  const res = await apiFetch(`/api/flows/${flowId}/restore/${versionId}`, {
    method: 'POST'
  });
  return parseApiResponse<FlowItem>(res);
}

export async function getFlowAnalytics(flowId: string, period: string = "7d", version?: string): Promise<FlowAnalytics> {
  const params = new URLSearchParams({ range: period });
  if (version) params.set("version", version);
  const res = await apiFetch(`/api/flows/${flowId}/analytics?${params.toString()}`);
  return parseApiResponse<FlowAnalytics>(res);
}

export async function getSystemSettings(): Promise<SystemSettings> {
  const res = await apiFetch('/api/settings');
  return parseApiResponse<SystemSettings>(res);
}

export async function updateSystemSettings(payload: SystemSettingsPayload): Promise<SystemSettings> {
  const res = await apiFetch('/api/settings', {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
  return parseApiResponse<SystemSettings>(res);
}

export async function listWhatsAppProviders(): Promise<WhatsAppProvider[]> {
  const res = await apiFetch('/api/whatsapp/providers');
  return parseApiResponse<WhatsAppProvider[]>(res);
}
export async function createWhatsAppProvider(payload: Record<string, unknown>): Promise<WhatsAppProvider> {
  const response = await apiFetch('/api/whatsapp/providers', { method: 'POST', body: JSON.stringify(payload) });
  if (response.status === 409) {
    console.error(
      "[PROVIDER CREATE ERROR]",
      await response.clone().text()
    );
  }
  return parseApiResponse<WhatsAppProvider>(response);
}

export async function updateWhatsAppProvider(providerId: string, payload: Record<string, unknown>): Promise<WhatsAppProvider> {
  const res = await apiFetch(`/api/whatsapp/providers/${providerId}`, { method: 'PATCH', body: JSON.stringify(payload) });
  return parseApiResponse<WhatsAppProvider>(res);
}

export async function activateWhatsAppProvider(providerId: string): Promise<WhatsAppProvider> {
  const res = await apiFetch(`/api/whatsapp/providers/${providerId}/activate`, { method: 'POST' });
  return parseApiResponse<WhatsAppProvider>(res);
}
export async function deleteWhatsAppProvider(providerId: string): Promise<void> {
  const res = await apiFetch(`/api/whatsapp/providers/${providerId}`, { method: 'DELETE' });
  return parseApiResponse<void>(res);
}

export async function testWhatsAppProvider(providerId: string) {
  const res = await apiFetch(`/api/whatsapp/providers/${providerId}/test`, { method: 'POST' });
  return parseApiResponse<{ok:boolean;status:string;message:string}>(res);
}
export async function listTemplates(): Promise<WhatsAppTemplate[]> { const res = await apiFetch('/api/whatsapp/templates'); return parseApiResponse<WhatsAppTemplate[]>(res); }
export async function createTemplate(payload: Record<string, unknown>): Promise<WhatsAppTemplate> { const res = await apiFetch('/api/whatsapp/templates', { method:'POST', body: JSON.stringify(payload)}); return parseApiResponse<WhatsAppTemplate>(res); }
export async function submitTemplate(templateId: string): Promise<WhatsAppTemplate> { const res = await apiFetch(`/api/whatsapp/templates/${templateId}/submit`, {method:'POST'}); return parseApiResponse<WhatsAppTemplate>(res); }
export async function syncTemplates(){ const res = await apiFetch('/api/whatsapp/templates/sync', {method:'POST'}); return parseApiResponse<{ok:boolean;message:string;count:number}>(res); }



export async function testSendWhatsAppTemplate(templateId: string, payload: { provider_id: string; to: string; variables: Record<string, string> }) {
  const res = await apiFetch(`/api/whatsapp/templates/${templateId}/test-send`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    const error = new Error(errorBody?.detail || `HTTP ${res.status}`) as Error & { meta_error?: string; meta_code?: number | string };
    error.meta_error = errorBody?.meta_error;
    error.meta_code = errorBody?.meta_code;
    throw error;
  }

  return res.json() as Promise<{ ok: boolean; provider_message_id?: string; raw?: Record<string, unknown> }>;
}

export async function listWhatsAppCampaigns(): Promise<WhatsAppCampaign[]> { const res = await apiFetch('/api/whatsapp/campaigns'); return parseApiResponse<WhatsAppCampaign[]>(res); }
export async function createWhatsAppCampaign(payload: Record<string, unknown>): Promise<WhatsAppCampaign> { const res = await apiFetch('/api/whatsapp/campaigns', { method:'POST', body: JSON.stringify(payload)}); return parseApiResponse<WhatsAppCampaign>(res); }
export async function getWhatsAppCampaign(campaignId: string): Promise<WhatsAppCampaign> { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}`); return parseApiResponse<WhatsAppCampaign>(res); }
export async function updateWhatsAppCampaign(campaignId: string, payload: Record<string, unknown>): Promise<WhatsAppCampaign> { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}`, { method:'PUT', body: JSON.stringify(payload)}); return parseApiResponse<WhatsAppCampaign>(res); }
export async function deleteWhatsAppCampaign(campaignId: string): Promise<void> { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}`, { method:'DELETE' }); return parseApiResponse<void>(res); }
export async function importWhatsAppCampaignRecipients(campaignId: string, recipients: Array<Record<string, unknown>>) { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}/recipients/import`, { method:'POST', body: JSON.stringify({ recipients })}); return parseApiResponse<{ok:boolean;imported:number}>(res); }
export async function startWhatsAppCampaign(campaignId: string) { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}/start`, { method:'POST' }); return parseApiResponse<WhatsAppCampaign>(res); }
export async function pauseWhatsAppCampaign(campaignId: string) { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}/pause`, { method:'POST' }); return parseApiResponse<WhatsAppCampaign>(res); }
export async function listWhatsAppCampaignRecipients(campaignId: string): Promise<WhatsAppCampaignRecipient[]> { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}/recipients`); return parseApiResponse<WhatsAppCampaignRecipient[]>(res); }

export async function importWhatsAppCampaignRecipientsFromContacts(campaignId: string, payload: Record<string, unknown>) { const res = await apiFetch(`/api/whatsapp/campaigns/${campaignId}/recipients/import-from-contacts`, { method:'POST', body: JSON.stringify(payload)}); return parseApiResponse<{ok:boolean;imported:number}>(res); }



export async function updateContact(contactId: string, payload: Record<string, unknown>) {
  const res = await apiFetch(`/api/contacts/${contactId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
  return parseApiResponse<CRMContact>(res);
}

export async function updateContactCustomFields(contactId: string, payload: Record<string, unknown>) {
  const res = await apiFetch(`/api/contacts/${contactId}/custom-fields`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
  return parseApiResponse(res);
}

export async function forgotPassword(email: string, turnstileToken: string): Promise<{ message: string }> {
  const res = await apiFetch('/api/forgot-password', { method: 'POST', body: JSON.stringify({ email, turnstile_token: turnstileToken }) });
  return parseApiResponse<{ message: string }>(res);
}

export async function resetPassword(token: string, new_password: string, confirm_password: string): Promise<{ message: string }> {
  const res = await apiFetch('/api/reset-password', { method: 'POST', body: JSON.stringify({ token, new_password, confirm_password }) });
  return parseApiResponse<{ message: string }>(res);
}


export async function getGoogleCalendarStatus(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/google-calendar/status${query}`);
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function disconnectGoogleCalendar(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/google-calendar/disconnect${query}`, { method: 'DELETE' });
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export function getGoogleCalendarConnectUrl(): string {
  const tenant = getTenantSlugOrId();
  if (!tenant) throw new Error('Tenant atual não encontrado para conectar o Google Calendar.');
  return buildApiUrl(`/api/integrations/google-calendar/connect?tenant_slug=${encodeURIComponent(tenant)}`);
}


export async function getGmailStatus(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/gmail/status${query}`);
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function disconnectGmail(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/gmail/disconnect${query}`, { method: 'DELETE' });
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export function getGmailConnectUrl(): string {
  const tenant = getTenantSlugOrId();
  if (!tenant) throw new Error('Tenant atual não encontrado para conectar o Gmail.');
  const path = `/api/integrations/gmail/connect-url?tenant_slug=${encodeURIComponent(tenant)}`;
  const url = buildApiUrl(path);
  console.info('GMAIL_OAUTH_CONNECT_URL_REQUESTED', {
    provider: 'gmail',
    callback_path: '/api/integrations/gmail/callback',
    scopes: [
      'https://www.googleapis.com/auth/gmail.readonly',
      'https://www.googleapis.com/auth/gmail.compose',
      'https://www.googleapis.com/auth/gmail.send',
      'openid',
      'email',
      'profile',
    ],
    connect_path: path,
    connect_url: url,
    tenant_slug: tenant,
  });
  return url;
}

export async function getGoogleDriveStatus(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/google-drive/status${query}`);
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function disconnectGoogleDrive(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/google-drive/disconnect${query}`, { method: 'POST' });
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export function getGoogleDriveConnectUrl(): string {
  const tenant = getTenantSlugOrId();
  if (!tenant) throw new Error('Tenant atual não encontrado para conectar o Google Drive.');
  return buildApiUrl(`/api/integrations/google-drive/connect-url?tenant_slug=${encodeURIComponent(tenant)}`);
}

export async function getSuitableStatus(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/suitable/status${query}`);
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function connectSuitable(apiKey: string): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/suitable/connect${query}`, {
    method: 'POST',
    body: JSON.stringify({ api_key: apiKey, metadata: { credential_source: 'manual_api_key' } })
  });
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function saveSuitableApiKey(apiKey: string): Promise<GoogleCalendarConnectionStatus> {
  return connectSuitable(apiKey);
}

export async function disconnectSuitable(): Promise<GoogleCalendarConnectionStatus> {
  const tenant = getTenantSlugOrId();
  const query = tenant ? `?tenant_slug=${encodeURIComponent(tenant)}` : '';
  const res = await apiFetch(`/api/integrations/suitable/disconnect${query}`, { method: 'POST' });
  return parseApiResponse<GoogleCalendarConnectionStatus>(res);
}

export async function getAccountMe(): Promise<AccountMe> {
  const res = await apiFetch('/api/account/me');
  return parseApiResponse<AccountMe>(res);
}

export async function updateAccountProfile(payload: Partial<AccountProfile>): Promise<AccountProfile> {
  const res = await apiFetch('/api/account/profile', { method: 'PUT', body: JSON.stringify(payload) });
  return parseApiResponse<AccountProfile>(res);
}

export async function updateAccountPreferences(payload: AccountPreferences): Promise<AccountPreferences> {
  const res = await apiFetch('/api/account/preferences', { method: 'PUT', body: JSON.stringify(payload) });
  return parseApiResponse<AccountPreferences>(res);
}

export async function getAccountSecurity(): Promise<AccountSecurity> {
  const res = await apiFetch('/api/account/security');
  return parseApiResponse<AccountSecurity>(res);
}

export async function updateAccountPassword(payload: { current_password: string; new_password: string; confirm_password: string }): Promise<{ message: string }> {
  const res = await apiFetch('/api/account/security/password', { method: 'POST', body: JSON.stringify(payload) });
  return parseApiResponse<{ message: string }>(res);
}

export async function revokeAccountSession(sessionId: string): Promise<{ message: string }> {
  const res = await apiFetch(`/api/account/security/sessions/${sessionId}/revoke`, { method: 'POST' });
  return parseApiResponse<{ message: string }>(res);
}

export async function revokeOtherAccountSessions(): Promise<{ message: string; revoked_count: number }> {
  const res = await apiFetch('/api/account/security/sessions/revoke-others', { method: 'POST' });
  return parseApiResponse<{ message: string; revoked_count: number }>(res);
}

export async function listAuditLogs(filters: { user_id?: string; action?: string; start_date?: string; end_date?: string } = {}): Promise<AuditLog[]> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const res = await apiFetch(`/api/security/audit${params.toString() ? `?${params.toString()}` : ''}`);
  return parseApiResponse<AuditLog[]>(res);
}

export async function listWorkspaceUsers(): Promise<WorkspaceUser[]> {
  const res = await apiFetch('/api/workspace/users');
  return parseApiResponse<WorkspaceUser[]>(res);
}

export async function inviteWorkspaceUser(payload: { name: string; email: string; role: string }): Promise<WorkspaceUser> {
  const res = await apiFetch('/api/workspace/users', { method: 'POST', body: JSON.stringify(payload) });
  return parseApiResponse<WorkspaceUser>(res);
}

export async function updateWorkspaceUser(userId: string, payload: { name?: string; role?: string; status?: string }): Promise<WorkspaceUser> {
  const res = await apiFetch(`/api/workspace/users/${userId}`, { method: 'PATCH', body: JSON.stringify(payload) });
  return parseApiResponse<WorkspaceUser>(res);
}

export async function deactivateWorkspaceUser(userId: string): Promise<WorkspaceUser> {
  const res = await apiFetch(`/api/workspace/users/${userId}/deactivate`, { method: 'POST' });
  return parseApiResponse<WorkspaceUser>(res);
}


export type TaskFilters = {
  status?: string;
  priority?: string;
  assigned_to?: string;
  overdue?: boolean;
  conversation_id?: string;
  contact_id?: string;
};

function buildTaskQuery(filters: TaskFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : '';
}

export async function listTasks(filters: TaskFilters = {}): Promise<TaskItem[]> {
  const res = await apiFetch(`/api/tasks${buildTaskQuery(filters)}`);
  return parseApiResponse<TaskItem[]>(res);
}

export async function updateTask(taskId: string, payload: TaskUpdatePayload): Promise<TaskItem> {
  const res = await apiFetch(`/api/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(payload) });
  return parseApiResponse<TaskItem>(res);
}

export async function completeTask(taskId: string): Promise<TaskItem> {
  const res = await apiFetch(`/api/tasks/${taskId}/complete`, { method: 'POST' });
  return parseApiResponse<TaskItem>(res);
}

export type AIExecution = {
  id: string;
  tenant_id: string;
  conversation_id: string | null;
  session_id: string | null;
  flow_id: string | null;
  flow_version_id: string | null;
  node_id: string;
  node_type: string;
  provider: string | null;
  model: string | null;
  started_at: string;
  finished_at: string | null;
  latency_ms: number | null;
  status: string;
  input_size: number | null;
  output_size: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  retrieval_mode: string | null;
  confidence: number | null;
  fallback_used: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type AIExecutionsResponse = {
  items: AIExecution[];
  page: number;
  page_size: number;
  total: number;
  metrics: {
    today: number;
    avg_latency_ms: number;
    fallback_percent: number;
    avg_confidence: number | null;
    top_providers: Array<{ name: string; count: number }>;
    top_models: Array<{ name: string; count: number }>;
  };
};

export async function listAIExecutions(filters: Record<string, string | number | boolean | undefined | null> = {}): Promise<AIExecutionsResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  const res = await apiFetch(`/api/ai/executions${params.toString() ? `?${params.toString()}` : ''}`);
  return parseApiResponse<AIExecutionsResponse>(res);
}

export async function getAIExecution(id: string): Promise<AIExecution> {
  const res = await apiFetch(`/api/ai/executions/${id}`);
  return parseApiResponse<AIExecution>(res);
}
