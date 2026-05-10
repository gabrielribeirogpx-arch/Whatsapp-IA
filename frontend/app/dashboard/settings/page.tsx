'use client';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Building2, CheckCircle2, Clock3, Layers3, MessageSquareText } from 'lucide-react';
import { activateWhatsAppProvider, createTemplate, createWhatsAppProvider, deleteWhatsAppProvider, getSystemSettings, listTemplates, listWhatsAppProviders, submitTemplate, syncTemplates, testWhatsAppProvider, updateSystemSettings } from '../../../lib/api';
import { SystemSettingsPayload, WhatsAppProvider, WhatsAppTemplate } from '../../../lib/types';
import ProvidersTab from '@/components/settings/whatsapp-business/ProvidersTab';
import TemplatesTab from '@/components/settings/whatsapp-business/TemplatesTab';

const INITIAL_FORM: SystemSettingsPayload = { token: '', phone_number_id: '', webhook_url: '', webhook_status: 'inactive', system_name: '', language: 'pt-BR' };
const baseProviderForm = { provider_type: 'meta_cloud', display_name: '', waba_id: '', phone_number_id: '', business_id: '', access_token: '', api_key: '' };
const baseTemplateForm = { name: '', category: 'utility', language: 'pt_BR', body_text: '', footer_text: '' };
const tabs = [{ id: 'system', label: 'Visão Geral', icon: Layers3 }, { id: 'connection', label: 'Conexões', icon: Building2 }, { id: 'templates', label: 'Templates', icon: MessageSquareText }];

export default function SettingsPage() {
  const [tab, setTab] = useState<'system' | 'connection' | 'templates'>('system');
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
    lastSync: new Date().toLocaleString('pt-BR')
  }), [providers, templates]);

  const validateTemplate = () => { if (!/^[a-z0-9_]+$/.test(templateForm.name)) return 'Nome do template deve ter lowercase e underscores.'; const re = /\{\{(\d+)\}\}/g; const m: number[] = []; let hit; while ((hit = re.exec(templateForm.body_text)) !== null) m.push(Number(hit[1])); const set = new Set(m); if (set.size !== m.length) return 'Variáveis duplicadas não são permitidas.'; for (let i = 1; i <= m.length; i++) if (!set.has(i)) return 'Variáveis com buracos são inválidas. Ex: {{1}} {{3}}'; return ''; };
  async function run(action: () => Promise<void>, ok: string, err: string) { setLoading(true); try { await action(); setToast(ok); } catch { setToast(err); } finally { setLoading(false); setTimeout(() => setToast(''), 3000); } }

  return <section className='w-full min-w-0 px-4 py-6 md:px-6'>
    <div className='mx-auto max-w-6xl space-y-5'>
      <header className='rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-white to-emerald-50/40 p-6 shadow-sm'>
        <p className='inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700'><MessageSquareText size={14} /> WhatsApp Business Console</p>
        <h1 className='mt-3 text-2xl font-semibold text-slate-900'>WhatsApp Business Console</h1>
        <p className='mt-1 text-sm text-slate-600'>Gerencie conexões oficiais Meta, templates aprováveis e futuros providers BSP.</p>
      </header>

      {toast && <div className='rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm'>{toast}</div>}

      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        {[
          ['Providers ativos', String(stats.activeProviders), Building2],
          ['Templates aprovados', String(stats.approvedTemplates), CheckCircle2],
          ['Templates pendentes', String(stats.pendingTemplates), Clock3],
          ['Status geral', stats.status, Layers3],
          ['Último sync', stats.lastSync, MessageSquareText]
        ].map(([label, value, Icon]: any) => <div key={label} className='rounded-2xl border border-slate-200 bg-white p-4 shadow-sm'><p className='inline-flex items-center gap-1 text-xs text-slate-500'><Icon size={12} />{label}</p><p className='mt-2 text-lg font-semibold text-slate-900'>{value}</p><div className='mt-3 h-1.5 rounded-full bg-slate-100'><div className='h-1.5 w-2/3 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600' /></div></div>)}
      </div>

      <div className='flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm'>
        {tabs.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => setTab(id as any)} className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition ${tab === id ? 'bg-slate-900 text-white shadow' : 'text-slate-600 hover:bg-slate-100'}`}><Icon size={14} />{label}</button>)}
      </div>

      {tab === 'system' && <form onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await updateSystemSettings({ ...form, token: form.token || null, phone_number_id: form.phone_number_id || null, webhook_url: form.webhook_url || null }); }, 'Configurações salvas com sucesso', 'Falha ao salvar configurações')} className='rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-3'>
        <input type='password' value={form.token ?? ''} onChange={e => setForm(p => ({ ...p, token: e.target.value }))} placeholder='Token atual (ENV fallback preservado)' className='w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm' />
        <input value={form.phone_number_id ?? ''} onChange={e => setForm(p => ({ ...p, phone_number_id: e.target.value }))} placeholder='Phone Number ID' className='w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm' />
        <button disabled={loading} className='primary-button'>Salvar</button>
      </form>}
      {tab === 'connection' && <ProvidersTab providers={providers} form={providerForm} setForm={setProviderForm} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await createWhatsAppProvider(providerForm); setProviderForm(baseProviderForm); await refresh(); }, 'Conexão salva com sucesso', 'Falha ao salvar conexão')} onTest={(id: string) => run(async () => { await testWhatsAppProvider(id); await refresh(); }, 'Conexão testada com sucesso', 'Falha ao testar conexão')} onActivate={(id: string) => run(async () => { await activateWhatsAppProvider(id); await refresh(); }, 'Conexão ativada com sucesso', 'Falha ao ativar conexão')} onDelete={(id: string) => run(async () => { await deleteWhatsAppProvider(id); await refresh(); }, 'Conexão removida com sucesso', 'Falha ao remover conexão')} />}
      {tab === 'templates' && <TemplatesTab templates={templates} form={templateForm} setForm={setTemplateForm} error={templateError} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); const msg = validateTemplate(); setTemplateError(msg); if (msg) throw new Error(msg); await createTemplate(templateForm); setTemplateForm(baseTemplateForm); await refresh(); }, 'Template criado com sucesso', 'Falha ao criar template')} onSync={() => run(async () => { await syncTemplates(); await refresh(); }, 'Sincronização concluída', 'Erro ao sincronizar templates')} onSubmitTemplate={(id: string) => run(async () => { await submitTemplate(id); await refresh(); }, 'Template enviado para aprovação', 'Falha ao enviar template')} />}
    </div>
  </section>;
}
