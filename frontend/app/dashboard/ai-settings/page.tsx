'use client';

import { FormEvent, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, Shield } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { FormSkeleton } from '@/components/ui/loading';

type AIProvider = 'openai' | 'gemini' | 'anthropic' | 'wazza_default';

type AISettings = {
  provider: AIProvider;
  chat_model: string | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  temperature: number;
  max_tokens: number;
  is_enabled: boolean;
  has_api_key: boolean;
};

const chatModels: Record<AIProvider, string[]> = {
  openai: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1'],
  gemini: ['gemini-3.1-flash-lite', 'gemini-3-flash', 'gemini-3.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-flash'],
  anthropic: ['claude-3-5-haiku-latest', 'claude-3-5-sonnet-latest', 'claude-3-7-sonnet-latest'],
  wazza_default: [],
};

const embeddingModels: Record<AIProvider, string[]> = {
  openai: ['text-embedding-3-small', 'text-embedding-3-large'],
  gemini: ['gemini-embedding-001', 'text-embedding-004', 'gemini-embedding-exp-03-07'],
  anthropic: [],
  wazza_default: [],
};

const defaultChatModel: Record<AIProvider, string> = { openai: 'gpt-4o-mini', gemini: 'gemini-3.1-flash-lite', anthropic: 'claude-3-5-haiku-latest', wazza_default: '' };
const defaultEmbeddingModel: Record<AIProvider, string> = { openai: 'text-embedding-3-small', gemini: 'gemini-embedding-001', anthropic: '', wazza_default: '' };
const embeddingProviderOptions: AIProvider[] = ['gemini', 'openai'];

function extractErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const record = payload as Record<string, unknown>;
  for (const candidate of [record.detail, record.message]) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate;
    if (candidate && typeof candidate === 'object') {
      const nested = candidate as Record<string, unknown>;
      if (typeof nested.message === 'string' && nested.message.trim()) return nested.message;
      if (typeof nested.detail === 'string' && nested.detail.trim()) return nested.detail;
    }
  }
  return fallback;
}

function isEmbeddingLike(model: string | null): boolean {
  const normalized = (model || '').toLowerCase();
  return normalized.includes('embedding') || normalized.includes('text-embedding');
}

function isChatLike(model: string | null): boolean {
  const normalized = (model || '').toLowerCase();
  return ['flash', 'pro', 'sonnet', 'haiku', 'opus', 'gpt-4', 'gpt-3'].some((marker) => normalized.includes(marker));
}

function asAIProvider(value: string | null | undefined): AIProvider | null {
  return value === 'openai' || value === 'gemini' || value === 'anthropic' || value === 'wazza_default' ? value : null;
}

type ModelInputProps = {
  label: string;
  value: string | null;
  suggestions: string[];
  disabled?: boolean;
  invalid?: boolean;
  placeholder: string;
  datalistId: string;
  help: string;
  error?: string;
  onChange: (value: string) => void;
};

function ModelInput({ label, value, suggestions, disabled, invalid, placeholder, datalistId, help, error, onChange }: ModelInputProps) {
  return (
    <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <input
        className={`mt-2 h-11 w-full rounded-xl border bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:ring-2 ${invalid ? 'border-red-300 focus:border-red-300 focus:ring-red-100' : 'border-slate-200 focus:border-emerald-300 focus:ring-emerald-100'}`}
        value={value || ''}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        aria-invalid={invalid}
        list={disabled ? undefined : datalistId}
        placeholder={placeholder}
      />
      <datalist id={datalistId}>{suggestions.map((model) => <option key={model} value={model} />)}</datalist>
      <span className="mt-2 block text-xs font-medium normal-case tracking-normal text-slate-500">{help}</span>
      {error ? <span className="mt-2 flex items-center gap-1.5 text-xs font-semibold normal-case tracking-normal text-red-600"><AlertCircle size={14} /> {error}</span> : null}
    </label>
  );
}

export default function AISettingsPage() {
  const [settings, setSettings] = useState<AISettings>({ provider: 'wazza_default', chat_model: '', embedding_provider: null, embedding_model: '', temperature: 0.2, max_tokens: 1200, is_enabled: true, has_api_key: false });
  const [apiKey, setApiKey] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const isWazzaDefault = settings.provider === 'wazza_default';
  const availableChatModels = chatModels[settings.provider];
  const embeddingProvider = asAIProvider(settings.embedding_provider) || (settings.provider === 'anthropic' ? null : settings.provider);
  const availableEmbeddingModels = embeddingProvider ? embeddingModels[embeddingProvider] : [];
  const supportsEmbeddingProvider = Boolean(embeddingProvider && availableEmbeddingModels.length > 0);
  const chatModelInvalid = !isWazzaDefault && (!(settings.chat_model || '').trim() || isEmbeddingLike(settings.chat_model));
  const embeddingModelInvalid = !isWazzaDefault && supportsEmbeddingProvider && (!(settings.embedding_model || '').trim() || isChatLike(settings.embedding_model));

  async function load() {
    setLoading(true);
    const response = await apiFetch('/api/ai/settings');
    if (response.ok) setSettings(await response.json());
    setLoading(false);
  }

  useEffect(() => { void load(); }, []);

  function update(partial: Partial<AISettings>) {
    setSettings((current) => ({ ...current, ...partial }));
  }

  function updateProvider(provider: AIProvider) {
    update({ provider, chat_model: defaultChatModel[provider], embedding_provider: provider === 'anthropic' || provider === 'wazza_default' ? null : provider, embedding_model: defaultEmbeddingModel[provider] });
  }

  function updateEmbeddingProvider(provider: AIProvider | '') {
    update({ embedding_provider: provider || null, embedding_model: provider ? defaultEmbeddingModel[provider] : '' });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (chatModelInvalid) { setStatus('Selecione um modelo de conversação válido.'); return; }
    if (embeddingModelInvalid) { setStatus('Selecione um modelo de embeddings válido.'); return; }
    setSaving(true); setStatus('');
    const response = await apiFetch('/api/ai/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...settings, embedding_provider: supportsEmbeddingProvider ? embeddingProvider : undefined, embedding_model: supportsEmbeddingProvider ? settings.embedding_model : undefined, api_key: isWazzaDefault ? undefined : apiKey || undefined }),
    });
    if (response.ok) {
      setSettings(await response.json());
      setApiKey('');
      setStatus('Configurações salvas.');
    } else {
      const payload = await response.json().catch(() => ({}));
      setStatus(extractErrorMessage(payload, 'Falha ao salvar configurações.'));
    }
    setSaving(false);
  }

  async function testConnection() {
    if (chatModelInvalid) { setStatus(isEmbeddingLike(settings.chat_model) ? 'Este é um modelo de embeddings. Selecione um modelo de conversação.' : 'Selecione um modelo de conversação.'); return; }
    setTesting(true); setStatus('');
    const response = await apiFetch('/api/ai/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: settings.provider, chat_model: settings.chat_model || undefined, api_key: isWazzaDefault ? undefined : apiKey || undefined }),
    });
    const payload = await response.json().catch(() => ({}));
    setStatus(response.ok ? extractErrorMessage(payload, 'Conexão validada.') : extractErrorMessage(payload, 'Não foi possível validar a conexão.'));
    setTesting(false);
  }

  async function removeKey() {
    const response = await apiFetch('/api/ai/settings/key', { method: 'DELETE' });
    if (response.ok) { setSettings(await response.json()); setApiKey(''); setStatus('Chave removida.'); }
  }

  if (loading) return <FormSkeleton />;

  return (
    <main className="min-h-screen w-full min-w-0 bg-slate-50 px-5 py-6 lg:px-6">
      <form onSubmit={save} className="w-full min-w-0 space-y-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between"><div><nav className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-400" aria-label="Breadcrumb"><span>Dashboard</span><span className="text-slate-300">&gt;</span><span>Configurações</span><span className="text-slate-300">&gt;</span><span className="text-emerald-600">IA</span></nav><h1 className="text-xl font-semibold leading-tight text-gray-900 md:text-2xl">✨ Configurações de IA</h1><p className="mt-1 text-sm text-gray-500">Configure o provedor utilizado pelos nodes IA/RAG deste workspace.</p></div></header>
        <div className="flex items-start gap-3 rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4 text-sm text-emerald-800 shadow-[0_12px_30px_rgba(15,23,42,0.04)]"><span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-emerald-200 bg-white text-emerald-600 shadow-sm"><Shield size={17} strokeWidth={2.4} /></span><p className="m-0 pt-1 leading-relaxed">Sua chave é criptografada e utilizada apenas durante as chamadas ao provedor configurado. Modelos de conversa e embeddings são separados para evitar uso incorreto.</p></div>

        <div className="grid w-full grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]"><div className="mb-5"><h2 className="text-base font-bold text-slate-900">Provedor de IA</h2><p className="mt-1 text-xs leading-relaxed text-slate-500">Defina qual motor será usado nas automações inteligentes.</p></div><div className="space-y-5">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Provider<select className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" value={settings.provider} onChange={(event) => updateProvider(event.target.value as AIProvider)}><option value="wazza_default">Wazza default</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="anthropic">Anthropic</option></select></label>
            <ModelInput label="Modelo de conversação" value={settings.chat_model} suggestions={availableChatModels} disabled={isWazzaDefault} invalid={chatModelInvalid} placeholder={isWazzaDefault ? 'Configuração global Wazza' : 'Digite ou selecione um modelo'} datalistId="ai-chat-models" help={settings.provider === 'gemini' ? 'Você pode selecionar uma sugestão ou digitar manualmente o ID do modelo disponível na sua conta do provedor. Consulte os modelos disponíveis no Google AI Studio.' : 'Você pode selecionar uma sugestão ou digitar manualmente o ID do modelo disponível na sua conta do provedor.'} error={chatModelInvalid ? 'Selecione um modelo de conversação.' : undefined} onChange={(value) => update({ chat_model: value })} />
            <div className="space-y-3">
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Provider de embeddings<select className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:opacity-60" value={embeddingProvider || ''} onChange={(event) => updateEmbeddingProvider(event.target.value as AIProvider | '')} disabled={isWazzaDefault}><option value="">{isWazzaDefault ? 'Configuração global Wazza' : 'Sem embeddings neste MVP'}</option>{embeddingProviderOptions.map((provider) => <option key={provider} value={provider}>{provider === 'gemini' ? 'Gemini' : 'OpenAI'}</option>)}</select>{settings.provider === 'anthropic' ? <span className="mt-2 block text-xs font-medium normal-case tracking-normal text-slate-500">Anthropic não possui embeddings nativo neste MVP. Use Gemini/OpenAI para embeddings.</span> : null}</label>
              <ModelInput label="Modelo de embeddings" value={settings.embedding_model} suggestions={availableEmbeddingModels} disabled={isWazzaDefault || !supportsEmbeddingProvider} invalid={embeddingModelInvalid} placeholder={isWazzaDefault ? 'Configuração global Wazza' : supportsEmbeddingProvider ? 'Digite ou selecione um modelo' : 'Embeddings não disponíveis para este provider'} datalistId="ai-embedding-models" help="Você pode selecionar uma sugestão ou digitar manualmente o ID do modelo disponível na sua conta do provedor." error={embeddingModelInvalid ? 'Selecione um modelo de embeddings.' : undefined} onChange={(value) => update({ embedding_model: value, embedding_provider: embeddingProvider })} />
            </div>
            <label className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-slate-50/80 p-4 text-sm font-semibold text-slate-800"><span><span className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Ativar IA</span><span className="mt-1 block text-sm text-slate-700">IA habilitada neste workspace</span></span><input className="h-5 w-5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-200" type="checkbox" checked={settings.is_enabled} onChange={(event) => update({ is_enabled: event.target.checked })} /></label>
          </div></section>

          <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]"><div className="mb-5"><h2 className="text-base font-bold text-slate-900">Segurança e execução</h2><p className="mt-1 text-xs leading-relaxed text-slate-500">Controle credenciais e limites usados durante as chamadas.</p></div><div className="space-y-5">
            {isWazzaDefault ? <div className="rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4 text-sm text-emerald-800"><p className="m-0 font-semibold">API Key gerenciada pelo Wazza</p><p className="m-0 mt-1 text-xs leading-relaxed">Usa a configuração global da Wazza. Nenhuma chave própria é necessária.</p></div> : <div><label className="block text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="ai-api-key">API Key</label><div className="mt-2 flex flex-col gap-3 sm:flex-row"><input id="ai-api-key" className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings.has_api_key ? '••••••••••••••••••' : 'Cole sua API key'} />{settings.has_api_key ? <button className="h-11 shrink-0 rounded-xl border border-red-100 bg-white px-4 text-sm font-semibold text-red-600 transition hover:border-red-200 hover:bg-red-50" type="button" onClick={() => void removeKey()}>Remover chave</button> : null}</div><span className={`mt-2 flex items-center gap-1.5 text-xs font-semibold ${settings.has_api_key ? 'text-emerald-600' : 'text-slate-500'}`}>{settings.has_api_key ? <CheckCircle2 size={14} /> : null}{settings.has_api_key ? 'Chave configurada' : 'Nenhuma chave configurada'}</span></div>}
            <div className="grid gap-4 sm:grid-cols-2"><label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Temperatura<input className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="number" step="0.1" min="0" max="2" value={settings.temperature} onChange={(event) => update({ temperature: Number(event.target.value) })} /></label><label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Máximo de tokens<input className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="number" min="1" max="8000" value={settings.max_tokens} onChange={(event) => update({ max_tokens: Number(event.target.value) })} /></label></div>
            <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-4"><p className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Status da chave</p><p className={`m-0 mt-2 flex items-center gap-2 text-base font-bold ${settings.has_api_key || isWazzaDefault ? 'text-emerald-700' : 'text-slate-700'}`}>{settings.has_api_key || isWazzaDefault ? <CheckCircle2 size={18} /> : null}{isWazzaDefault ? 'Chave global Wazza' : settings.has_api_key ? 'Chave configurada' : 'Nenhuma chave configurada'}</p></div>
          </div></section>
        </div>
        {status ? <div className="rounded-2xl border border-slate-100 bg-white p-4 text-sm font-medium text-slate-700 shadow-[0_12px_30px_rgba(15,23,42,0.04)]">{status}</div> : null}
        <div className="flex flex-col-reverse items-stretch justify-end gap-3 sm:flex-row sm:items-center"><button disabled={testing || chatModelInvalid} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/40 disabled:cursor-not-allowed disabled:opacity-50" type="button" onClick={() => void testConnection()}>{testing ? <Loader2 className="animate-spin" size={16} /> : null}{testing ? 'Testando...' : 'Testar conexão'}</button><button disabled={saving} className="inline-flex h-11 items-center justify-center rounded-xl bg-emerald-600 px-6 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" type="submit">{saving ? 'Salvando...' : 'Salvar'}</button></div>
      </form>
    </main>
  );
}
