'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Building2, CheckCircle2, Clock3, CreditCard, Layers3, LockKeyhole, MessageSquareText, Rocket, ShieldCheck, Sparkles, User, UsersRound, type LucideIcon } from 'lucide-react';
import ProvidersTab from '@/components/settings/whatsapp-business/ProvidersTab';
import TemplatesTab from '@/components/settings/whatsapp-business/TemplatesTab';
import { ClientDateTime } from '@/components/settings/whatsapp-business/ui';
import { activateWhatsAppProvider, createTemplate, createWhatsAppProvider, deleteWhatsAppProvider, getSystemSettings, listTemplates, listWhatsAppProviders, submitTemplate, syncTemplates, testWhatsAppProvider, updateSystemSettings, updateWhatsAppProvider } from '@/lib/api';
import { SystemSettingsPayload, WhatsAppProvider, WhatsAppTemplate } from '@/lib/types';
import { friendlyToMeta, renderExample, validateMetaVariables } from '@/lib/templateVariableMapper';
import { SettingsTabId } from './SettingsSidebar';
import { AccountTabId } from '@/components/account/AccountSidebar';

const INITIAL_FORM: SystemSettingsPayload = { token: '', phone_number_id: '', webhook_url: '', webhook_status: 'inactive', system_name: '', language: 'pt-BR' };
const baseProviderForm = { provider_type: 'meta_cloud', display_name: '', waba_id: '', phone_number_id: '', business_id: '', access_token: '', api_key: '' };
const baseTemplateForm = { name: '', category: 'utility', language: 'pt_BR', provider_id: '', body_text: '', friendly_body_text: '', footer_text: '', variables_json: [] as any[] };
const whatsappTabs = [{ id: 'system', label: 'Visão Geral', icon: Layers3 }, { id: 'connection', label: 'Conexões', icon: Building2 }, { id: 'templates', label: 'Templates', icon: MessageSquareText }];

const emptyStates = {
  profile: {
    icon: User,
    eyebrow: 'Identity Center',
    title: 'Meu Perfil',
    description: 'Dados pessoais, avatar, assinatura e presença no workspace serão concentrados aqui.',
    roadmap: ['Avatar corporativo e status de disponibilidade', 'Assinatura de atendimento e idioma preferido', 'Auditoria de alterações do perfil']
  },
  preferences: {
    icon: Sparkles,
    eyebrow: 'Personalização',
    title: 'Preferências',
    description: 'Ajustes de notificações, densidade visual e experiência individual estão no roadmap.',
    roadmap: ['Notificações por canal e prioridade', 'Tema, densidade e atalhos do painel', 'Preferências por produto e inbox']
  },
  users: {
    icon: UsersRound,
    eyebrow: 'Admin Console',
    title: 'Usuários',
    description: 'Gerenciamento de equipe, seats e convites será liberado em um módulo enterprise dedicado.',
    roadmap: ['Convites com expiração e domínio permitido', 'Seats por função e área de negócio', 'Status de usuário e trilha de auditoria']
  },
  permissions: {
    icon: ShieldCheck,
    eyebrow: 'Governança',
    title: 'Permissões',
    description: 'Papéis granulares e políticas de acesso por área serão exibidos nesta aba.',
    roadmap: ['RBAC por módulo e ação crítica', 'Políticas por time, fila e campanha', 'Aprovações para operações sensíveis']
  },
  security: {
    icon: LockKeyhole,
    eyebrow: 'Trust & Security',
    title: 'Segurança',
    description: 'Sessões pessoais, login, MFA e controles de segurança da sua conta ficam aqui.',
    roadmap: ['Sessões ativas e revogação remota', 'MFA e chaves de recuperação', 'Alertas de login e dispositivos confiáveis']
  },
  billing: {
    icon: CreditCard,
    eyebrow: 'Revenue Operations',
    title: 'Billing',
    description: 'Planos, faturas, limites de uso e add-ons serão apresentados sem sair do Settings Hub.',
    roadmap: ['Plano atual e consumo por workspace', 'Faturas, método de pagamento e centros de custo', 'Limites, add-ons e forecast de uso']
  },
  integrations: {
    icon: Layers3,
    eyebrow: 'Integration Catalog',
    title: 'Integrações',
    description: 'Apps conectados, automações e conectores do workspace serão administrados nesta área.',
    roadmap: ['Catálogo de integrações por área', 'OAuth, webhooks e automações autorizadas', 'Monitoramento de saúde dos conectores']
  }
} satisfies Partial<Record<SettingsTabId | AccountTabId, { icon: LucideIcon; eyebrow: string; title: string; description: string; roadmap: string[] }>>;

export default function SettingsContent({ activeTab }: { activeTab: SettingsTabId | AccountTabId }) {
  if (activeTab === 'apikeys' || activeTab === 'whatsapp-business') return <WhatsAppBusinessConsole />;

  const state = emptyStates[activeTab];
  if (!state) return null;
  const Icon = state.icon;

  return (
    <div className='overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-white/95 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)]'>
      <div className='relative border-b border-slate-100 bg-gradient-to-br from-white via-slate-50 to-emerald-50/50 p-6 md:p-8'>
        <div className='pointer-events-none absolute right-8 top-6 h-24 w-24 rounded-full bg-emerald-300/20 blur-2xl' />
        <p className='inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white/80 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm'><Icon size={14} /> {state.eyebrow}</p>
        <h2 className='mt-4 text-2xl font-semibold tracking-tight text-slate-950'>{state.title}</h2>
        <p className='mt-2 max-w-2xl text-sm leading-relaxed text-slate-600'>{state.description}</p>
      </div>

      <div className='grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_320px] md:p-6'>
        <div className='relative overflow-hidden rounded-3xl border border-dashed border-slate-200/50 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 p-6 text-white shadow-[0_24px_54px_-38px_rgba(15,23,42,0.9)]'>
          <div className='pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-emerald-400/25 blur-3xl' />
          <div className='flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/10 text-emerald-200'>
            <Rocket size={24} />
          </div>
          <p className='mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-200'>Em breve</p>
          <h3 className='mt-2 text-xl font-semibold tracking-tight'>Experiência premium em construção</h3>
          <p className='mt-2 max-w-xl text-sm leading-relaxed text-slate-300'>Esta área já possui navegação própria para evitar conteúdo incorreto. O módulo completo entra no roadmap Enterprise com a mesma experiência administrativa do restante do produto.</p>
          <button type='button' className='mt-6 inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white px-4 py-2 text-sm font-semibold text-slate-950 shadow-sm'>Roadmap Enterprise <ArrowUpRight size={14} /></button>
        </div>

        <div className='rounded-3xl border border-slate-200 bg-white p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]'>
          <p className='text-sm font-semibold text-slate-950'>Roadmap Enterprise</p>
          <div className='mt-4 space-y-3'>
            {state.roadmap.map(item => (
              <div key={item} className='flex gap-3 rounded-2xl border border-slate-100 bg-slate-50/80 p-3'>
                <span className='mt-1 h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.12)]' />
                <p className='text-sm leading-snug text-slate-600'>{item}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function WhatsAppBusinessConsole() {
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
    lastSyncAt: providers
      .map(p => p?.metadata_json?.last_sync_at || p.last_connection_check_at || p.updated_at)
      .filter(Boolean)
      .sort((a, b) => new Date(b as string).getTime() - new Date(a as string).getTime())[0] ?? null
  }), [providers, templates]);

  const validateTemplate = () => { if (!/^[a-z0-9_]+$/.test(templateForm.name)) return 'Nome do template deve ter lowercase e underscores.'; const mapped = friendlyToMeta(templateForm.friendly_body_text || templateForm.body_text || ''); if (mapped.errors.length) return `${mapped.errors[0]}\nUse uma variável da lista ou remova o marcador.`; return validateMetaVariables(mapped.bodyText); };
  const parseFriendlyError = (error: unknown, fallback: string) => {
    if (!(error instanceof Error)) return fallback;
    const match = error.message.match(/HTTP \d+:\s*([\s\S]*)$/);
    if (!match?.[1]) return fallback;
    try {
      const parsed = JSON.parse(match[1]);
      const detailPayload = parsed?.detail;
      const detail = typeof detailPayload === 'string' ? detailPayload : detailPayload?.detail;
      const metaError = detailPayload?.meta_error;
      if (detail && metaError) return `Erro ao enviar template: ${detail}\n${metaError}`;
      if (detail) return `Erro ao enviar template: ${detail}`;
    } catch {
      return fallback;
    }
    return fallback;
  };
  async function run(action: () => Promise<void>, ok: string, err: string) { setLoading(true); try { await action(); setToast(ok); } catch (error) { setToast(parseFriendlyError(error, err)); } finally { setLoading(false); setTimeout(() => setToast(''), 5000); } }

  return <div className='w-full min-w-0 space-y-5'>
    <header className='relative overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-gradient-to-br from-white/95 via-white/90 to-emerald-50/70 p-6 shadow-[0_20px_50px_-40px_rgba(2,6,23,0.55)] backdrop-blur-sm md:p-7'>
      <div className='pointer-events-none absolute -top-10 right-8 h-28 w-28 rounded-full bg-emerald-400/15 blur-2xl' />
      <p className='inline-flex items-center gap-2 rounded-full border border-emerald-200/80 bg-white/80 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm'><MessageSquareText size={14} /> API Keys & WhatsApp Business</p>
      <div className='mt-3 flex flex-wrap items-center gap-3'>
        <h1 className='text-2xl font-semibold tracking-tight text-slate-900 md:text-[1.75rem]'>WhatsApp Business Console</h1>
        <span className='inline-flex items-center rounded-full border border-emerald-300/60 bg-gradient-to-r from-emerald-50 to-white px-3 py-1 text-xs font-semibold text-emerald-700'>Enterprise Ready</span>
      </div>
      <p className='mt-2 max-w-2xl text-sm leading-relaxed text-slate-600'>Gerencie tokens, conexões oficiais Meta, templates aprováveis e futuros providers BSP sem quebrar a experiência atual.</p>
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
      {whatsappTabs.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => setTab(id as any)} className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-200 ${tab === id ? 'bg-slate-900 text-white shadow-md shadow-slate-900/20' : 'text-slate-600 hover:bg-slate-100/90 hover:text-slate-900 active:scale-[0.99]'}`}><Icon size={14} />{label}</button>)}
    </div>

    {tab === 'system' && <form onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await updateSystemSettings({ ...form, token: form.token || null, phone_number_id: form.phone_number_id || null, webhook_url: form.webhook_url || null }); }, 'Configurações salvas com sucesso', 'Falha ao salvar configurações')} className='w-full min-w-0 space-y-3 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]'>
      <input type='password' value={form.token ?? ''} onChange={e => setForm(p => ({ ...p, token: e.target.value }))} placeholder='Token atual (ENV fallback preservado)' className='premium-input w-full' />
      <input value={form.phone_number_id ?? ''} onChange={e => setForm(p => ({ ...p, phone_number_id: e.target.value }))} placeholder='Phone Number ID' className='premium-input w-full' />
      <button disabled={loading} className='primary-button'>Salvar</button>
    </form>}
    {tab === 'connection' && <ProvidersTab providers={providers} form={providerForm} setForm={setProviderForm} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); await createWhatsAppProvider(providerForm); setProviderForm(baseProviderForm); await refresh(); }, 'Conexão salva com sucesso', 'Falha ao salvar conexão')} onTest={(id: string) => run(async () => { await testWhatsAppProvider(id); await refresh(); }, 'Conexão testada com sucesso', 'Falha ao testar conexão')} onActivate={(id: string) => run(async () => { await activateWhatsAppProvider(id); await refresh(); }, 'Conexão ativada com sucesso', 'Falha ao ativar conexão')} onDelete={(id: string) => run(async () => { await deleteWhatsAppProvider(id); await refresh(); }, 'Conexão removida com sucesso', 'Falha ao remover conexão')} onEdit={(id: string, payload: Record<string, unknown>) => run(async () => { await updateWhatsAppProvider(id, payload); await testWhatsAppProvider(id); await refresh(); }, 'Conexão atualizada', 'Falha ao atualizar conexão')} />}
    {tab === 'templates' && <TemplatesTab templates={templates} providers={providers} form={templateForm} setForm={setTemplateForm} error={templateError} loading={loading} onSubmit={(e: FormEvent) => run(async () => { e.preventDefault(); const msg = validateTemplate(); setTemplateError(msg); if (msg) throw new Error(msg); const mapped = friendlyToMeta(templateForm.friendly_body_text || templateForm.body_text || ''); await createTemplate({ ...templateForm, provider_id: templateForm.provider_id || null, body_text: mapped.bodyText, body_raw_meta: mapped.bodyText, body_preview: renderExample(mapped.bodyText, mapped.variables), variables_json: mapped.variables }); setTemplateForm(baseTemplateForm); await refresh(); }, 'Template criado com sucesso', 'Falha ao criar template')} onSync={() => run(async () => { await syncTemplates(); await refresh(); }, 'Sincronização concluída', 'Erro ao sincronizar templates')} onSubmitTemplate={(id: string) => run(async () => { await submitTemplate(id); await refresh(); }, 'Template enviado para aprovação', 'Falha ao enviar template')} />}
  </div>;
}
