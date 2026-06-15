'use client';

import { FormEvent, useEffect, useState } from 'react';
import { CheckCircle2, Loader2, Shield } from 'lucide-react';
import { apiFetch } from '@/lib/api';

type AIProvider = 'openai' | 'gemini' | 'anthropic' | 'wazza_default';

type AISettings = {
  provider: AIProvider;
  model: string | null;
  temperature: number;
  max_tokens: number;
  is_enabled: boolean;
  has_api_key: boolean;
};

const providerModels: Record<AIProvider, string> = {
  openai: 'gpt-4o-mini',
  gemini: 'gemini-1.5-flash',
  anthropic: 'claude-3-5-haiku-latest',
  wazza_default: '',
};

export default function AISettingsPage() {
  const [settings, setSettings] = useState<AISettings>({ provider: 'wazza_default', model: '', temperature: 0.2, max_tokens: 1200, is_enabled: true, has_api_key: false });
  const [apiKey, setApiKey] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

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

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true); setStatus('');
    const response = await apiFetch('/api/ai/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...settings, api_key: apiKey || undefined }),
    });
    if (response.ok) {
      setSettings(await response.json());
      setApiKey('');
      setStatus('Configurações salvas.');
    } else {
      const payload = await response.json().catch(() => ({}));
      setStatus(payload.detail || 'Falha ao salvar configurações.');
    }
    setSaving(false);
  }

  async function testConnection() {
    setTesting(true); setStatus('');
    const response = await apiFetch('/api/ai/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: settings.provider, model: settings.model || undefined, api_key: apiKey || undefined }),
    });
    const payload = await response.json().catch(() => ({}));
    setStatus(response.ok ? (payload.message || 'Conexão validada.') : (payload.detail || 'Não foi possível validar a conexão.'));
    setTesting(false);
  }

  async function removeKey() {
    const response = await apiFetch('/api/ai/settings/key', { method: 'DELETE' });
    if (response.ok) {
      setSettings(await response.json());
      setApiKey('');
      setStatus('Chave removida.');
    }
  }

  if (loading) return <main className="px-5 py-6 text-sm text-slate-500 lg:px-6">Carregando configurações de IA...</main>;

  return (
    <main className="min-h-screen w-full min-w-0 bg-slate-50 px-5 py-6 lg:px-6">
      <form onSubmit={save} className="w-full min-w-0 space-y-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <nav className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-400" aria-label="Breadcrumb">
              <span>Dashboard</span>
              <span className="text-slate-300">&gt;</span>
              <span>Configurações</span>
              <span className="text-slate-300">&gt;</span>
              <span className="text-emerald-600">IA</span>
            </nav>
            <h1 className="text-xl font-semibold leading-tight text-gray-900 md:text-2xl">✨ Configurações de IA</h1>
            <p className="mt-1 text-sm text-gray-500">Configure o provedor utilizado pelos nodes IA/RAG deste workspace.</p>
          </div>
        </header>

        <div className="flex items-start gap-3 rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4 text-sm text-emerald-800 shadow-[0_12px_30px_rgba(15,23,42,0.04)]">
          <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-emerald-200 bg-white text-emerald-600 shadow-sm">
            <Shield size={17} strokeWidth={2.4} />
          </span>
          <p className="m-0 pt-1 leading-relaxed">Sua chave é criptografada e utilizada apenas durante as chamadas ao provedor configurado.</p>
        </div>

        <div className="grid w-full grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]">
            <div className="mb-5">
              <h2 className="text-base font-bold text-slate-900">Provedor de IA</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">Defina qual motor será usado nas automações inteligentes.</p>
            </div>

            <div className="space-y-5">
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Provider
                <select className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" value={settings.provider} onChange={(event) => update({ provider: event.target.value as AIProvider, model: providerModels[event.target.value as AIProvider] })}>
                  <option value="wazza_default">Wazza default</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </label>

              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Modelo
                <input className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" value={settings.model || ''} onChange={(event) => update({ model: event.target.value })} placeholder={providerModels[settings.provider] || 'Configuração global Wazza'} />
              </label>

              <label className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-slate-50/80 p-4 text-sm font-semibold text-slate-800">
                <span>
                  <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Ativar IA</span>
                  <span className="mt-1 block text-sm text-slate-700">IA habilitada neste workspace</span>
                </span>
                <input className="h-5 w-5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-200" type="checkbox" checked={settings.is_enabled} onChange={(event) => update({ is_enabled: event.target.checked })} />
              </label>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]">
            <div className="mb-5">
              <h2 className="text-base font-bold text-slate-900">Segurança e execução</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">Controle credenciais e limites usados durante as chamadas.</p>
            </div>

            <div className="space-y-5">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="ai-api-key">API Key</label>
                <div className="mt-2 flex flex-col gap-3 sm:flex-row">
                  <input id="ai-api-key" className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings.has_api_key ? '••••••••••••••••••' : 'Cole sua API key'} />
                  {settings.has_api_key ? <button className="h-11 shrink-0 rounded-xl border border-red-100 bg-white px-4 text-sm font-semibold text-red-600 transition hover:border-red-200 hover:bg-red-50" type="button" onClick={() => void removeKey()}>Remover chave</button> : null}
                </div>
                <span className={`mt-2 flex items-center gap-1.5 text-xs font-semibold ${settings.has_api_key ? 'text-emerald-600' : 'text-slate-500'}`}>
                  {settings.has_api_key ? <CheckCircle2 size={14} /> : null}
                  {settings.has_api_key ? 'Chave configurada' : 'Nenhuma chave configurada'}
                </span>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Temperatura
                  <input className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="number" step="0.1" min="0" max="2" value={settings.temperature} onChange={(event) => update({ temperature: Number(event.target.value) })} />
                </label>
                <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Máximo de tokens
                  <input className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100" type="number" min="1" max="8000" value={settings.max_tokens} onChange={(event) => update({ max_tokens: Number(event.target.value) })} />
                </label>
              </div>

              <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-4">
                <p className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Status da chave</p>
                <p className={`m-0 mt-2 flex items-center gap-2 text-base font-bold ${settings.has_api_key ? 'text-emerald-700' : 'text-slate-700'}`}>
                  {settings.has_api_key ? <CheckCircle2 size={18} /> : null}
                  {settings.has_api_key ? 'Chave configurada' : 'Nenhuma chave configurada'}
                </p>
              </div>
            </div>
          </section>
        </div>

        {status ? <div className="rounded-2xl border border-slate-100 bg-white p-4 text-sm font-medium text-slate-700 shadow-[0_12px_30px_rgba(15,23,42,0.04)]">{status}</div> : null}

        <div className="flex flex-col-reverse items-stretch justify-end gap-3 sm:flex-row sm:items-center">
          <button disabled={testing} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/40 disabled:cursor-not-allowed disabled:opacity-50" type="button" onClick={() => void testConnection()}>{testing ? <Loader2 className="animate-spin" size={16} /> : null}{testing ? 'Testando...' : 'Testar conexão'}</button>
          <button disabled={saving} className="inline-flex h-11 items-center justify-center rounded-xl bg-emerald-600 px-6 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50" type="submit">{saving ? 'Salvando...' : 'Salvar'}</button>
        </div>
      </form>
    </main>
  );
}
