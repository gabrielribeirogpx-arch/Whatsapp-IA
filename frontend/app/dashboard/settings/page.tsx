'use client';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Building2, CheckCircle2, Clock3, Layers3, MessageSquareText } from 'lucide-react';
import { activateWhatsAppProvider, createTemplate, createWhatsAppProvider, deleteWhatsAppProvider, getSystemSettings, listTemplates, listWhatsAppProviders, submitTemplate, syncTemplates, testWhatsAppProvider, updateSystemSettings } from '../../../lib/api';
import { SystemSettingsPayload, WhatsAppProvider, WhatsAppTemplate } from '../../../lib/types';
import ProvidersTab from '@/components/settings/whatsapp-business/ProvidersTab';
import TemplatesTab from '@/components/settings/whatsapp-business/TemplatesTab';
import CampaignsTab from '@/components/settings/whatsapp-business/CampaignsTab';
import { ClientDateTime } from '@/components/settings/whatsapp-business/ui';
import { friendlyToMeta, renderExample, validateMetaVariables } from '@/lib/templateVariableMapper';

const INITIAL_FORM: SystemSettingsPayload = { token: '', phone_number_id: '', webhook_url: '', webhook_status: 'inactive', system_name: '', language: 'pt-BR' };
const baseProviderForm = { provider_type: 'meta_cloud', display_name: '', waba_id: '', phone_number_id: '', business_id: '', access_token: '', api_key: '' };
const baseTemplateForm = { name: '', category: 'utility', language: 'pt_BR', provider_id: '', body_text: '', friendly_body_text: '', footer_text: '', variables_json: [] as any[] };
const tabs = [{ id: 'system', label: 'Visão Geral', icon: Layers3 }, { id: 'connection', label: 'Conexões', icon: Building2 }, { id: 'templates', label: 'Templates', icon: MessageSquareText }, { id: 'campaigns', label: 'Campanhas', icon: MessageSquareText }];

export default function SettingsPage() {
  const [tab, setTab] = useState<'system' | 'connection' | 'templates' | 'campaigns'>('system');
  const [toast, setToast] = useState('');
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<SystemSettingsPayload>(INITIAL_FORM);
  const [providers, setProviders] = useState<WhatsAppProvider[]>([]);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [providerForm, setProviderForm] = useState(baseProviderForm);
  const [templateForm, setTemplateForm] = useState(baseTemplateForm);
  const [templateError, setTemplateError] = useState('');
  const refresh = async () => { setProviders(await listWhatsAppProviders()); setTemplates(await listTemplates()); };

  useEffect(() => { (async () => { const data = await getSystemSettings(); setForm({ ...INITIAL_FORM, ...data }); await refresh(); })(); }, []);

  const stats = useMemo(() => ({
    activeProviders: providers.filter(p => p.is_active).length,
    approvedTemplates: templates.filter(t => t.status === 'approved').length,
    pendingTemplates: templates.filter(t => t.status === 'pending' || t.status === 'submitted').length,
    status: providers.some(p => p.status === 'connected') ? 'Operacional' : 'Sem conexão',
    lastSyncAt: providers
      .map(p => p?.metadata_json?.last_sync_at || p.last_connection_check_at || p.updated_at)
      .filter(Boolean)
      .sort((a, b) => new Date(b as string).getTime() - new Date(a as string).getTime())[0] ?? null
  }), [providers, templates]);

  const validateTemplate = () => { if (!/^[a-z0-9_]+$/.test(templateForm.name)) return 'Nome do template deve ter lowercase e underscores.'; const mapped = friendlyToMeta(templateForm.friendly_body_text || templateForm.body_text || ''); if (mapped.errors.length) return `${mapped.errors[0]}
Use uma variável da lista ou remova o marcador.`; return validateMetaVariables(mapped.bodyText); };
  async function run(action: () => Promise<void>, ok: string, err: string) { setLoading(true); try { await action(); setToast(ok); } catch { setToast(err); } finally { setLoading(false); setTimeout(() => setToast(''), 3000); } }

  return <section className='w-full min-w-0 px-4 py-6 sm:px-6 lg:px-8'>
    <div className='w-full min-w-0 space-y-5'>
      <header className='relative overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-gradient-to-br from-white/95 via-white/90 to-emerald-50/70 p-6 shadow-[0_20px_50px_-40px_rgba(2,6,23,0.55)] backdrop-blur-sm md:p-7'>
        <div className='pointer-events-none absolute -top-10 right-8 h-28 w-28 rounded-full bg-emerald-400/15 blur-2xl' />
        <p className='inline-flex items-center gap-2 rounded-full border border-emerald-200/80 bg-white/80 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm'><MessageSquareText size={14} /> WhatsApp Business Console</p>
        <div className='mt-3 flex flex-wrap items-center gap-3'>
          <h1 className='text-2xl font-semibold tracking-tight text-slate-900 md:text-[1.75rem]'>WhatsApp Business Console</h1>
          <span className='inline-flex items-center rounded-full border border-emerald-300/60 bg-gradient-to-r from-emerald-50 to-white px-3 py-1 text-xs font-semibold text-emerald-700'>Enterprise Ready</span>
        </div>
        <p className='mt-2 max-w-2xl text-sm leading-relaxed text-slate-600'>Gerencie conexões oficiais Meta, templates aprováveis e futuros providers BSP.</p>
      </header>

      {toast && <div className='rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm'>{toast}</div>}

      <div className='grid w-full min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        {[
          ['Providers ativos', String(stats.activeProviders), Building2],
          ['Templates aprovados', String(stats.approvedTemplates), CheckCircle2],
          ['Templates pendentes', String(stats.pendingTemplates), Clock3],
          ['Status geral', stats.status, Layers3],
          ['Último sync', stats.lastSyncAt, MessageSquareText]
        ].map(([label, value, Icon]: any) => <div key={label} className='group rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-4 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.75)] transition-all duration-300 hover:-translate-y-0.5 hover:border-emerald-200 hover:shadow-[0_20px_36px_-26px_rgba(16,185,129,0.35)]'><p className='inline-flex items-center gap-1 text-xs font-medium text-slate-500'><Icon size={12} />{label}</p><p className='mt-2 text-lg font-semibold tracking-tight text-slate-900'>{label === 'Último sync' ? <ClientDateTime value={value} fallback='Nunca sincronizado' /> : value}</p><div className='mt-3 h-1.5 rounded-full bg-slate-100/90'><div className='h-1.5 w-2/3 rounded-full bg-gradient-to-r from-emerald-400 via-emerald-500 to-emerald-600 transition-all duration-300 group-hover:w-4/5' /></div></div>)}
      </div>

      <div className='flex w-full min-w-0 flex-wrap gap-2 rounded-2xl border border-[color:var(--surface-border)] bg-white/90 p-2 shadow-[0_10px_24px_-24px_rgba(15,23,42,0.8)] backdrop-blur'>
        {tabs.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => setTab(id as any)} className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-200 ${tab === id ? 'bg-slate-900 text-white shadow-md shadow-slate-900/20' : 'text-slate-600 hover:bg-slate-100/90 hover:text-slate-900 active:scale-[0.99]'}`}><Icon size={14} />{label}</button>)}
      </div>

      {tab === 'system' && <form onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await updateSystemSettings({ ...form, token: form.token || null, phone_number_id: form.phone_number_id || null, webhook_url: form.webhook_url || null }); }, 'Configurações salvas com sucesso', 'Falha ao salvar configurações')} className='w-full min-w-0 space-y-3 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]'>
        <input type='password' value={form.token ?? ''} onChange={e => setForm(p => ({ ...p, token: e.target.value }))} placeholder='Token atual (ENV fallback preservado)' className='premium-input w-full' />
        <input value={form.phone_number_id ?? ''} onChange={e => setForm(p => ({ ...p, phone_number_id: e.target.value }))} placeholder='Phone Number ID' className='premium-input w-full' />
        <button disabled={loading} className='primary-button'>Salvar</button>
      </form>}
      {tab === 'connection' && <ProvidersTab providers={providers} form={providerForm} setForm={setProviderForm} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await createWhatsAppProvider(providerForm); setProviderForm(baseProviderForm); await refresh(); }, 'Conexão salva com sucesso', 'Falha ao salvar conexão')} onTest={(id: string) => run(async () => { await testWhatsAppProvider(id); await refresh(); }, 'Conexão testada com sucesso', 'Falha ao testar conexão')} onActivate={(id: string) => run(async () => { await activateWhatsAppProvider(id); await refresh(); }, 'Conexão ativada com sucesso', 'Falha ao ativar conexão')} onDelete={(id: string) => run(async () => { await deleteWhatsAppProvider(id); await refresh(); }, 'Conexão removida com sucesso', 'Falha ao remover conexão')} />}
      {tab === 'templates' && <TemplatesTab templates={templates} providers={providers} form={templateForm} setForm={setTemplateForm} error={templateError} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); const msg = validateTemplate(); setTemplateError(msg); if (msg) throw new Error(msg); const mapped = friendlyToMeta(templateForm.friendly_body_text || templateForm.body_text || ''); await createTemplate({ ...templateForm, provider_id: templateForm.provider_id || null, body_text: mapped.bodyText, body_raw_meta: mapped.bodyText, body_preview: renderExample(mapped.bodyText, mapped.variables), variables_json: mapped.variables }); setTemplateForm(baseTemplateForm); await refresh(); }, 'Template criado com sucesso', 'Falha ao criar template')} onSync={() => run(async () => { await syncTemplates(); await refresh(); }, 'Sincronização concluída', 'Erro ao sincronizar templates')} onSubmitTemplate={(id: string) => run(async () => { await submitTemplate(id); await refresh(); }, 'Template enviado para aprovação', 'Falha ao enviar template')} />}
      {tab === 'campaigns' && <CampaignsTab />}
    </div>
  </section>;
}
