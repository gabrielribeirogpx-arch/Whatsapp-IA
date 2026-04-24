'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';

import { getSystemSettings, updateSystemSettings } from '../../../lib/api';
import { SystemSettingsPayload } from '../../../lib/types';

const INITIAL_FORM: SystemSettingsPayload = {
  token: '',
  phone_number_id: '',
  webhook_url: '',
  webhook_status: 'inactive',
  system_name: '',
  language: 'pt-BR'
};

export default function SettingsPage() {
  const [form, setForm] = useState<SystemSettingsPayload>(INITIAL_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [statusType, setStatusType] = useState<'success' | 'error'>('success');

  useEffect(() => {
    async function loadSettings() {
      try {
        const data = await getSystemSettings();
        setForm({
          token: data.token ?? '',
          phone_number_id: data.phone_number_id ?? '',
          webhook_url: data.webhook_url ?? '',
          webhook_status: data.webhook_status ?? 'inactive',
          system_name: data.system_name ?? '',
          language: data.language ?? 'pt-BR'
        });
      } catch {
        setStatusType('error');
        setStatusMessage('Não foi possível carregar as configurações.');
      } finally {
        setLoading(false);
      }
    }

    void loadSettings();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setStatusMessage(null);

    try {
      await updateSystemSettings({
        ...form,
        token: form.token?.trim() || null,
        webhook_url: form.webhook_url?.trim() || null
      });
      setStatusType('success');
      setStatusMessage('Configurações salvas com sucesso.');
    } catch {
      setStatusType('error');
      setStatusMessage('Erro ao salvar configurações. Tente novamente.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-page-wrapper">
      <nav className="dash-sidebar">
        <div className="dash-sidebar-logo">
          <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
          <img src="/Logo2.svg" alt="Logo" className="logo-full" />
        </div>
        <span className="dash-nav-section">Principal</span>
        <Link href="/dashboard" className="dash-nav-item">
          <span className="dash-nav-label">Dashboard</span>
        </Link>
        <Link href="/dashboard/settings" className="dash-nav-item active">
          <span className="dash-nav-label">Configurações</span>
        </Link>
      </nav>

      <main className="settings-main-content">
        <header className="settings-header">
          <h1>Configurações do sistema</h1>
          <p>Gerencie integração WhatsApp, webhook e preferências gerais.</p>
        </header>

        <form className="settings-form" onSubmit={handleSubmit}>
          <section className="settings-card">
            <h2>API WhatsApp</h2>
            <div className="settings-grid">
              <label>
                Token
                <input
                  type="password"
                  value={form.token ?? ''}
                  onChange={(event) => setForm((prev) => ({ ...prev, token: event.target.value }))}
                  placeholder="Insira o token da API WhatsApp"
                />
              </label>
              <label>
                Phone Number ID
                <input
                  value={form.phone_number_id}
                  onChange={(event) => setForm((prev) => ({ ...prev, phone_number_id: event.target.value }))}
                  placeholder="Ex.: 123456789012345"
                  required
                />
              </label>
            </div>
          </section>

          <section className="settings-card">
            <h2>Webhook</h2>
            <div className="settings-grid">
              <label>
                URL
                <input
                  type="url"
                  value={form.webhook_url ?? ''}
                  onChange={(event) => setForm((prev) => ({ ...prev, webhook_url: event.target.value }))}
                  placeholder="https://seu-dominio.com/webhook"
                />
              </label>
              <label>
                Status
                <select
                  value={form.webhook_status}
                  onChange={(event) => setForm((prev) => ({ ...prev, webhook_status: event.target.value }))}
                >
                  <option value="active">Ativo</option>
                  <option value="inactive">Inativo</option>
                </select>
              </label>
            </div>
          </section>

          <section className="settings-card">
            <h2>Geral</h2>
            <div className="settings-grid">
              <label>
                Nome do sistema
                <input
                  value={form.system_name}
                  onChange={(event) => setForm((prev) => ({ ...prev, system_name: event.target.value }))}
                  placeholder="Nome da sua operação"
                  required
                />
              </label>
              <label>
                Idioma
                <select value={form.language} onChange={(event) => setForm((prev) => ({ ...prev, language: event.target.value }))}>
                  <option value="pt-BR">Português (Brasil)</option>
                  <option value="en-US">English (US)</option>
                  <option value="es-ES">Español</option>
                </select>
              </label>
            </div>
          </section>

          <div className="settings-actions">
            <button type="submit" disabled={loading || saving}>
              {saving ? 'Salvando...' : 'Salvar configurações'}
            </button>
            {statusMessage ? <p className={`settings-feedback ${statusType}`}>{statusMessage}</p> : null}
          </div>
        </form>
      </main>
    </div>
  );
}
