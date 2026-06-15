'use client';

import { FormEvent, useEffect, useState } from 'react';
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

  if (loading) return <main className="p-6 text-slate-500">Carregando configurações de IA...</main>;

  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <form onSubmit={save} className="mx-auto max-w-3xl space-y-6 rounded-2xl border bg-white p-6 shadow-sm">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">Workspace</p>
          <h1 className="text-2xl font-bold text-slate-900">Configurações de IA</h1>
          <p className="mt-2 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-800">Sua chave é criptografada e usada apenas para responder mensagens dos seus fluxos.</p>
        </header>

        <label className="block text-sm font-medium text-slate-700">Provedor
          <select className="mt-1 w-full rounded-lg border px-3 py-2" value={settings.provider} onChange={(event) => update({ provider: event.target.value as AIProvider, model: providerModels[event.target.value as AIProvider] })}>
            <option value="wazza_default">Wazza default</option>
            <option value="openai">OpenAI</option>
            <option value="gemini">Gemini</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>

        <label className="block text-sm font-medium text-slate-700">Modelo
          <input className="mt-1 w-full rounded-lg border px-3 py-2" value={settings.model || ''} onChange={(event) => update({ model: event.target.value })} placeholder={providerModels[settings.provider] || 'Configuração global Wazza'} />
        </label>

        <label className="block text-sm font-medium text-slate-700">API Key
          <input className="mt-1 w-full rounded-lg border px-3 py-2" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings.has_api_key ? 'Chave configurada — informe uma nova para trocar' : 'Cole sua API key'} />
          <span className="mt-1 block text-xs text-slate-500">{settings.has_api_key ? 'Chave configurada' : 'Nenhuma chave configurada'}</span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">Temperatura
            <input className="mt-1 w-full rounded-lg border px-3 py-2" type="number" step="0.1" min="0" max="2" value={settings.temperature} onChange={(event) => update({ temperature: Number(event.target.value) })} />
          </label>
          <label className="block text-sm font-medium text-slate-700">Máximo de tokens
            <input className="mt-1 w-full rounded-lg border px-3 py-2" type="number" min="1" max="8000" value={settings.max_tokens} onChange={(event) => update({ max_tokens: Number(event.target.value) })} />
          </label>
        </div>

        <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <input type="checkbox" checked={settings.is_enabled} onChange={(event) => update({ is_enabled: event.target.checked })} />
          Ativar IA neste workspace
        </label>

        {status ? <div className="rounded-lg border bg-slate-50 p-3 text-sm text-slate-700">{status}</div> : null}

        <div className="flex flex-wrap gap-3">
          <button disabled={saving} className="rounded-lg bg-indigo-600 px-5 py-2 font-semibold text-white disabled:opacity-50" type="submit">{saving ? 'Salvando...' : 'Salvar'}</button>
          <button disabled={testing} className="rounded-lg border px-5 py-2 font-semibold text-slate-700 disabled:opacity-50" type="button" onClick={() => void testConnection()}>{testing ? 'Testando...' : 'Testar conexão'}</button>
          {settings.has_api_key ? <button className="rounded-lg border border-red-200 px-5 py-2 font-semibold text-red-700" type="button" onClick={() => void removeKey()}>Remover chave</button> : null}
        </div>
      </form>
    </main>
  );
}
