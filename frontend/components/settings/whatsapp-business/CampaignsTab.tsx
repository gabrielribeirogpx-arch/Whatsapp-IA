'use client';

import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  CalendarRange,
  Clock3,
  CheckCircle2,
  Eye,
  Filter,
  Loader2,
  Megaphone,
  MessageCircle,
  PauseCircle,
  Plus,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  TriangleAlert
} from 'lucide-react';
import CampaignCard from './campaigns/CampaignCard';
import CampaignCreateModal from './campaigns/CampaignCreateModal';
import CampaignStats from './campaigns/CampaignStats';
import {
  apiFetch,
  createWhatsAppCampaign,
  importWhatsAppCampaignRecipients,
  importWhatsAppCampaignRecipientsFromContacts,
  listTemplates,
  listWhatsAppCampaigns,
  listWhatsAppProviders,
  pauseWhatsAppCampaign,
  startWhatsAppCampaign,
  testSendWhatsAppTemplate
} from '@/lib/api';
import { CRMContact, WhatsAppCampaign, WhatsAppProvider, WhatsAppTemplate } from '@/lib/types';

type LeadInput = { phone: string; fields: Record<string, string> };
type VariableFieldOption = { value: string; label: string; csvColumn: string };
type VariableMappingPayload = { type: 'contact_field' | 'custom_field' | 'fixed'; field?: string; value?: string };

const APPROVED_STATUS = 'approved';
const FIXED_VALUE_FIELD = 'fixed_value';
const VARIABLE_FIELD_OPTIONS: VariableFieldOption[] = [
  { value: 'full_name', label: 'Nome completo', csvColumn: 'nome_completo' },
  { value: 'first_name', label: 'Primeiro nome', csvColumn: 'primeiro_nome' },
  { value: 'phone', label: 'Telefone', csvColumn: 'telefone' },
  { value: 'email', label: 'E-mail', csvColumn: 'email' },
  { value: 'order_number', label: 'Campo personalizado: order_number', csvColumn: 'numero_pedido' },
  { value: FIXED_VALUE_FIELD, label: 'Valor fixo', csvColumn: 'valor_fixo' }
];

function badgeClass(ok: boolean) {
  return ok
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-slate-200 bg-slate-100 text-slate-500';
}

function getTemplateText(template?: WhatsAppTemplate | null): string {
  if (!template) return '';

  const metadataRaw = (template as WhatsAppTemplate & { metadata_json?: unknown }).metadata_json;
  let metadata: Record<string, unknown> = {};
  if (typeof metadataRaw === 'string') {
    try {
      metadata = JSON.parse(metadataRaw) as Record<string, unknown>;
    } catch {
      metadata = {};
    }
  } else if (metadataRaw && typeof metadataRaw === 'object') {
    metadata = metadataRaw as Record<string, unknown>;
  }

  const bodyComponentText = Array.isArray((template as { components?: Array<Record<string, unknown>> }).components)
    ? ((template as { components?: Array<Record<string, unknown>> }).components || []).find((component) => String(component.type || '').toUpperCase() === 'BODY')?.text
    : '';

  const metadataBodyComponentText = Array.isArray(metadata.components)
    ? (metadata.components as Array<Record<string, unknown>>).find((component) => String(component.type || '').toUpperCase() === 'BODY')?.text
    : '';

  const templateWithFallbackFields = template as WhatsAppTemplate & { body?: string; content?: string };

  return [
    templateWithFallbackFields.body,
    template.body_text,
    template.body_preview,
    templateWithFallbackFields.content,
    bodyComponentText,
    metadata.body,
    metadataBodyComponentText
  ]
    .filter((value) => typeof value === 'string' && value.trim().length > 0)
    .join('\n');
}

function extractVariables(text: string): string[] {
  const regex = /\{\{(\d+)\}\}/g;
  const variables = new Set<string>();
  let match = regex.exec(text);

  while (match) {
    variables.add(match[1]);
    match = regex.exec(text);
  }

  return Array.from(variables).sort((a, b) => Number(a) - Number(b));
}

type CampaignsTabProps = {
  standalone?: boolean;
};

export default function CampaignsTab({ standalone = false }: CampaignsTabProps) {
  const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [savedContacts, setSavedContacts] = useState<CRMContact[]>([]);
  const [contactsLoadError, setContactsLoadError] = useState<string | null>(null);
  const [selectedContactIds, setSelectedContactIds] = useState<string[]>([]);
  const [recipientMode, setRecipientMode] = useState<'csv' | 'saved'>('csv');
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [providers, setProviders] = useState<WhatsAppProvider[]>([]);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [leadsText, setLeadsText] = useState('');
  const [testPhone, setTestPhone] = useState('');
  const [variableMapping, setVariableMapping] = useState<Record<string, string>>({});
  const [manualVariableValues, setManualVariableValues] = useState<Record<string, string>>({});
  const [testVariableValues, setTestVariableValues] = useState<Record<string, string>>({});
  const [testStatus, setTestStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [testSending, setTestSending] = useState(false);
  const [campaignActionError, setCampaignActionError] = useState<string | null>(null);

  const [searchTerm, setSearchTerm] = useState('');
  const [periodFilter] = useState('Últimos 7 dias');
  const [tagFilter] = useState('Todas as tags');
  const [statusFilter, setStatusFilter] = useState('all');

  const filteredCampaigns = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase();
    return campaigns.filter((c) => {
      const matchesSearch = !needle || `${c.name} ${c.id}`.toLowerCase().includes(needle);
      const matchesStatus = statusFilter === 'all' || c.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [campaigns, searchTerm, statusFilter]);

  const statusTone = (status: string) => ({
    running: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    scheduled: 'bg-sky-50 text-sky-700 border-sky-200',
    paused: 'bg-amber-50 text-amber-700 border-amber-200',
    draft: 'bg-slate-100 text-slate-700 border-slate-200',
    completed: 'bg-violet-50 text-violet-700 border-violet-200',
    failed: 'bg-rose-50 text-rose-700 border-rose-200'
  }[status] || 'bg-slate-100 text-slate-700 border-slate-200');

  const formatNum = (value: number) => new Intl.NumberFormat('pt-BR').format(value || 0);


  const fetchContacts = async () => {
    const url = '/api/contacts';
    console.log('CONTACTS FETCH URL', url);

    const response = await apiFetch(url, {
      cache: 'no-store'
    });
    console.log('CONTACTS FETCH STATUS', response.status);

    const data = await response.json();
    console.log('CONTACTS FETCH BODY', data);

    if (!response.ok) {
      throw new Error(data?.detail || 'Falha ao carregar contatos');
    }

    const contactsArray = Array.isArray(data)
      ? data
      : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data?.contacts)
          ? data.contacts
          : [];

    setSavedContacts(contactsArray);
    setContactsLoadError(null);
  };
  const refresh = async () => {
    setLoading(true);
    try {
      setCampaigns(await listWhatsAppCampaigns());
      try {
        await fetchContacts();
      } catch (error) {
        console.error('[CAMPAIGNS CONTACTS LOAD ERROR]', error);
        setSavedContacts([]);
        setContactsLoadError('Não foi possível carregar contatos');
      }
    } finally {
      setLoading(false);
    }
  };

  const reloadContacts = async () => {
    try {
      await fetchContacts();
    } catch (error) {
      console.error('[CAMPAIGNS CONTACTS RELOAD ERROR]', error);
      setSavedContacts([]);
      setContactsLoadError('Não foi possível carregar contatos');
    }
  };

  const loadAssets = async () => {
    setAssetsLoading(true);
    try {
      const [providersData, templatesData] = await Promise.all([listWhatsAppProviders(), listTemplates()]);
      setProviders(providersData);
      setTemplates(templatesData);
      const connected = providersData.filter((p) => p.status === 'connected');
      if (!providerId && connected.length === 1) setProviderId(connected[0].id);
    } finally {
      setAssetsLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (showCreate) void loadAssets();
  }, [showCreate]);

  const metrics = useMemo(() => {
    const active = campaigns.filter((c) => ['running', 'scheduled'].includes(c.status)).length;
    return {
      active,
      sent: campaigns.reduce((acc, c) => acc + (c.total_sent || 0), 0),
      delivered: campaigns.reduce((acc, c) => acc + (c.total_delivered || 0), 0),
      read: campaigns.reduce((acc, c) => acc + (c.total_read || 0), 0),
      failed: campaigns.reduce((acc, c) => acc + (c.total_failed || 0), 0)
    };
  }, [campaigns]);

  const kpiCards = [
    { key: 'Ativas', value: metrics.active, delta: '+20%', icon: Activity },
    { key: 'Enviados', value: metrics.sent, delta: '+18%', icon: Send },
    { key: 'Entregues', value: metrics.delivered, delta: '+18%', icon: CheckCircle2 },
    { key: 'Lidos', value: metrics.read, delta: '+12%', icon: Eye },
    { key: 'Falhas', value: metrics.failed, delta: '-4%', icon: TriangleAlert }
  ] as const;

  const statusFilters = [
    { label: 'Todas', value: 'all' },
    { label: 'Rodando', value: 'running' },
    { label: 'Agendadas', value: 'scheduled' },
    { label: 'Rascunhos', value: 'draft' },
    { label: 'Pausadas', value: 'paused' },
    { label: 'Concluídas', value: 'completed' }
  ];

  const runningCampaigns = campaigns.filter((campaign) => ['running', 'scheduled'].includes(campaign.status)).slice(0, 3);
  const deliveryRate = metrics.sent > 0 ? Math.round((metrics.delivered / metrics.sent) * 100) : 100;
  const readRate = metrics.delivered > 0 ? Math.round((metrics.read / metrics.delivered) * 100) : 0;
  const failureRate = metrics.sent > 0 ? Math.round((metrics.failed / metrics.sent) * 100) : 0;
  const accountHealth = failureRate > 12 ? 'Atenção' : failureRate > 5 ? 'Monitorando' : 'Saudável';
  const recentActivities = campaigns.slice(0, 4).map((campaign) => ({
    id: campaign.id,
    title: campaign.name,
    description: `Status ${campaign.status} • ${formatNum(campaign.total_sent || 0)} envios`,
    tone: statusTone(campaign.status)
  }));

  const approvedTemplates = useMemo(() => {
    return templates.filter((t) => t.status?.toLowerCase() === APPROVED_STATUS && (!providerId || t.provider_id === providerId));
  }, [templates, providerId]);

  const selectedTemplate = approvedTemplates.find((t) => t.id === templateId);
  const templateText = useMemo(() => getTemplateText(selectedTemplate), [selectedTemplate]);
  const templateVariables = useMemo(() => {
    const detectedVariables = extractVariables(templateText);
    if (detectedVariables.length === 0 && selectedTemplate?.name === 'pedido_entregue_v4') {
      return ['1', '2'];
    }
    return detectedVariables;
  }, [selectedTemplate, templateText]);

  useEffect(() => {
    if (templateId && !approvedTemplates.some((t) => t.id === templateId)) setTemplateId('');
  }, [approvedTemplates, templateId]);

  useEffect(() => {
    if (!templateVariables.length) {
      setVariableMapping({});
      setManualVariableValues({});
      setTestVariableValues({});
      return;
    }
    setVariableMapping((prev) => templateVariables.reduce((acc, key) => ({ ...acc, [key]: prev[key] || 'first_name' }), {}));
    setManualVariableValues((prev) => templateVariables.reduce((acc, key) => ({ ...acc, [key]: prev[key] || '' }), {}));
    setTestVariableValues((prev) => templateVariables.reduce((acc, key) => ({
      ...acc,
      [key]: prev[key] || (key === '1' ? 'Gabriel' : key === '2' ? '#4821' : '')
    }), {}));
  }, [templateVariables]);

  const variableValues = useMemo(() => {
    return templateVariables.reduce<Record<string, string>>((acc, key) => {
      const field = variableMapping[key];
      acc[key] = field === FIXED_VALUE_FIELD ? manualVariableValues[key] || '' : testVariableValues[key] || '';
      return acc;
    }, {});
  }, [manualVariableValues, templateVariables, testVariableValues, variableMapping]);

  const parseLeads = (): LeadInput[] => {
    const expectedColumns = ['telefone', ...templateVariables.map((key) => VARIABLE_FIELD_OPTIONS.find((item) => item.value === variableMapping[key])?.csvColumn || `variavel_${key}`)];
    return leadsText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const values = line.split(',').map((p) => p.trim());
        const phone = values[0] || '';
        const fields = expectedColumns.slice(1).reduce<Record<string, string>>((acc, column, index) => {
          acc[column] = values[index + 1] || '';
          return acc;
        }, {});
        return { phone, fields };
      })
      .filter((item) => item.phone);
  };

  const onCsvUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setLeadsText((prev) => (prev ? `${prev}\n${text.trim()}` : text.trim()));
  };

  const renderPreview = () => {
    return templateText.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, key: string) => `**${variableValues[key] || `Variável ${key}`}**`);
  };

  const onQuickTest = async () => {
    if (!testPhone || !selectedTemplate || !providerId) return;

    console.log('[CAMPAIGN TEST VARIABLES]', {
      template: selectedTemplate,
      text: templateText,
      variables: templateVariables,
      testVariables: testVariableValues
    });

    if (templateVariables.length && Object.keys(testVariableValues).length === 0) {
      setTestStatus({ type: 'error', message: 'Preencha as variáveis de teste.' });
      return;
    }

    if (templateVariables.length) {
      for (const key of templateVariables) {
        const value = (testVariableValues[key] || '').trim();
        if (!value) {
          setTestStatus({ type: 'error', message: `Preencha a variável ${key}` });
          return;
        }
      }
    }

    const payloadVariables: Record<string, string> = {};
    templateVariables.forEach((key) => {
      payloadVariables[key] = (testVariableValues[key] || '').trim();
    });

    console.log('[WHATSAPP TEMPLATE TEST PAYLOAD]', {
      provider_id: providerId,
      to: testPhone,
      variables: payloadVariables
    });

    setTestSending(true);
    setTestStatus(null);
    try {
      const result = await testSendWhatsAppTemplate(selectedTemplate.id, {
        provider_id: providerId,
        to: testPhone,
        variables: payloadVariables
      });
      setTestStatus({ type: 'success', message: `Teste enviado com sucesso. message_id: ${result.provider_message_id || 'n/a'}` });
    } catch (error) {
      const err = error as Error & { meta_error?: string; meta_code?: number | string };
      const details = [err.message, err.meta_error ? `meta_error: ${err.meta_error}` : '', err.meta_code ? `meta_code: ${err.meta_code}` : ''].filter(Boolean).join(' | ');
      setTestStatus({ type: 'error', message: details || 'Falha ao enviar teste de template.' });
    } finally {
      setTestSending(false);
    }
  };

  const onCreate = async () => {
    if (!name || !providerId || !templateId || hasRecipientVariableErrors) return;
    const created = await createWhatsAppCampaign({ name, provider_id: providerId, template_id: templateId });
    const leads = parseLeads();
    if (recipientMode === 'csv' && leads.length) {
      await importWhatsAppCampaignRecipients(
        created.id,
        leads.map((item) => ({ phone: item.phone, variables_json: item.fields }))
      );
    }
    if (recipientMode === 'saved' && selectedContactIds.length) {
      await importWhatsAppCampaignRecipientsFromContacts(created.id, {
        contact_ids: selectedContactIds,
        variable_mapping: variableMapping,
        manual_variable_values: manualVariableValues,
        variable_mapping_payload: templateVariables.reduce<Record<string, VariableMappingPayload>>((acc, key) => {
          const selected = variableMapping[key];
          if (selected === FIXED_VALUE_FIELD) {
            acc[key] = { type: 'fixed', value: (manualVariableValues[key] || '').trim() };
          } else if (selected === 'order_number') {
            acc[key] = { type: 'custom_field', field: 'order_number' };
          } else {
            acc[key] = { type: 'contact_field', field: selected || 'first_name' };
          }
          return acc;
        }, {})
      });
    }
    setName('');
    setProviderId('');
    setTemplateId('');
    setLeadsText('');
    setShowCreate(false);
    await refresh();
  };
  const onStartCampaign = async (campaignId: string) => {
    try {
      setCampaignActionError(null);
      await startWhatsAppCampaign(campaignId);
      await refresh();
    } catch (error) {
      setCampaignActionError((error as Error).message || 'Falha ao iniciar campanha.');
    }
  };
  const onPauseCampaign = async (campaignId: string) => {
    await pauseWhatsAppCampaign(campaignId);
    await refresh();
  };

  const hasCreateErrors = !name || !providerId || !templateId;
  const hasVariableErrors = templateVariables.some((key) => !variableMapping[key] || (variableMapping[key] === FIXED_VALUE_FIELD && !manualVariableValues[key]));
  const hasRecipientVariableErrors = (() => {
    if (!templateVariables.length) return false;
    if (recipientMode === 'saved') return false;
    const leads = parseLeads();
    if (!leads.length) return false;
    return leads.some((lead) => templateVariables.some((key) => {
      const field = variableMapping[key];
      if (field === FIXED_VALUE_FIELD) return !(manualVariableValues[key] || '').trim();
      const column = VARIABLE_FIELD_OPTIONS.find((item) => item.value === field)?.csvColumn || `variavel_${key}`;
      return !(lead.fields[column] || '').trim();
    }));
  })();
  const csvHeaders = ['telefone', ...templateVariables.map((key) => VARIABLE_FIELD_OPTIONS.find((item) => item.value === variableMapping[key])?.csvColumn || `variavel_${key}`)];

  return <div className={`space-y-6 rounded-[28px] border border-[color:var(--surface-border)] bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.12),transparent_32%),linear-gradient(180deg,#ffffff,rgba(248,250,252,0.88))] p-4 shadow-[0_28px_90px_-54px_rgba(15,23,42,0.65)] sm:p-6 ${standalone ? '' : 'shadow-none'}`}>
    <header className='overflow-hidden rounded-[18px] border border-emerald-100 bg-slate-950 text-white shadow-[0_22px_60px_-34px_rgba(15,23,42,0.85)]'>
      <div className='relative p-6 sm:p-8'>
        <div className='absolute right-0 top-0 h-48 w-48 rounded-full bg-emerald-400/20 blur-3xl' />
        <div className='relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between'>
          <div className='max-w-2xl space-y-4'>
            <span className='inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold text-emerald-100 backdrop-blur'><Megaphone size={14}/> Campaign Center Premium</span>
            <div>
              <h1 className='text-3xl font-semibold tracking-tight sm:text-4xl'>Campanhas WhatsApp com visão executiva</h1>
              <p className='mt-2 text-sm leading-6 text-slate-300'>Orquestre campanhas, acompanhe saúde operacional e encontre gargalos sem sair do painel.</p>
            </div>
          </div>
          <div className='flex flex-col gap-2 sm:flex-row'>
            <button onClick={() => void refresh()} className='inline-flex items-center justify-center gap-2 rounded-[18px] border border-white/15 bg-white/10 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/15'><RefreshCcw size={14}/>Atualizar</button>
            <button onClick={() => setShowCreate(true)} className='inline-flex items-center justify-center gap-2 rounded-[18px] bg-emerald-400 px-4 py-3 text-sm font-semibold text-slate-950 shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-300'><Plus size={14}/>Nova campanha</button>
          </div>
        </div>
      </div>
    </header>

    {campaignActionError ? <p className='rounded-[18px] border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700'>{campaignActionError}</p> : null}

    <CampaignStats>
      <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5'>
        {kpiCards.map((card) => {
          const Icon = card.icon;
          return <div key={card.key} className='group rounded-[18px] border border-slate-200/80 bg-white p-5 shadow-[0_18px_45px_-34px_rgba(15,23,42,0.55)] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_24px_55px_-36px_rgba(15,23,42,0.7)]'>
            <div className='mb-4 flex items-center justify-between'>
              <div className='rounded-[16px] bg-emerald-50 p-2.5'><Icon size={18} className='text-emerald-600'/></div>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${card.delta.startsWith('-') ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-600'}`}>{card.delta}</span>
            </div>
            <p className='text-xs font-medium uppercase tracking-[0.18em] text-slate-400'>{card.key}</p>
            <p className='mt-1 text-3xl font-semibold tracking-tight text-slate-950'>{formatNum(card.value)}</p>
            <p className='mt-2 text-xs text-slate-500'>Comparativo visual dos últimos 7 dias</p>
          </div>;
        })}
      </div>
    </CampaignStats>

    <div className='grid grid-cols-1 gap-4 xl:grid-cols-[1.15fr_0.85fr]'>
      <section className='rounded-[18px] border border-slate-200/80 bg-white p-5 shadow-[0_18px_45px_-36px_rgba(15,23,42,0.55)]'>
        <div className='mb-4 flex items-center justify-between gap-3'><div><p className='text-sm font-semibold text-slate-950'>Campanhas em andamento</p><p className='text-xs text-slate-500'>Fila ativa, agendada e pronta para acompanhamento.</p></div><span className='rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700'>{runningCampaigns.length} ativas</span></div>
        <div className='space-y-3'>{runningCampaigns.length ? runningCampaigns.map((campaign) => { const total = campaign.total_recipients || 0; const progress = total > 0 ? Math.min(100, Math.round((((campaign.total_sent || 0) + (campaign.total_failed || 0)) / total) * 100)) : 0; return <div key={campaign.id} className='rounded-[18px] border border-slate-100 bg-slate-50/70 p-4'><div className='flex items-center justify-between gap-3'><div><p className='font-semibold text-slate-900'>{campaign.name}</p><p className='text-xs text-slate-500'>{formatNum(campaign.total_sent || 0)} enviados de {formatNum(total)} destinatários</p></div><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(campaign.status)}`}>{campaign.status}</span></div><div className='mt-3 h-2 rounded-full bg-white'><div className='h-2 rounded-full bg-emerald-500' style={{ width: `${progress}%` }}/></div></div>; }) : <p className='rounded-[18px] border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500'>Nenhuma campanha em andamento no momento.</p>}</div>
      </section>
      <aside className='grid gap-4 sm:grid-cols-2 xl:grid-cols-1'>
        <div className='rounded-[18px] border border-emerald-100 bg-white p-5 shadow-[0_18px_45px_-36px_rgba(15,23,42,0.55)]'><div className='flex items-center gap-3'><div className='rounded-[16px] bg-emerald-50 p-3'><ShieldCheck size={20} className='text-emerald-600'/></div><div><p className='text-sm font-semibold text-slate-950'>Saúde da Conta WhatsApp</p><p className='text-xs text-slate-500'>Indicadores baseados nas campanhas carregadas.</p></div></div><div className='mt-5 grid grid-cols-3 gap-2 text-center'><div className='rounded-[16px] bg-slate-50 p-3'><p className='text-lg font-semibold text-slate-950'>{deliveryRate}%</p><p className='text-[11px] text-slate-500'>Entrega</p></div><div className='rounded-[16px] bg-slate-50 p-3'><p className='text-lg font-semibold text-slate-950'>{readRate}%</p><p className='text-[11px] text-slate-500'>Leitura</p></div><div className='rounded-[16px] bg-slate-50 p-3'><p className='text-lg font-semibold text-slate-950'>{failureRate}%</p><p className='text-[11px] text-slate-500'>Falhas</p></div></div><p className='mt-4 inline-flex rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700'><MessageCircle size={13} className='mr-1'/>{accountHealth}</p></div>
        <div className='rounded-[18px] border border-slate-200/80 bg-white p-5 shadow-[0_18px_45px_-36px_rgba(15,23,42,0.55)]'><div className='mb-4 flex items-center gap-2'><Clock3 size={16} className='text-slate-500'/><p className='text-sm font-semibold text-slate-950'>Timeline de atividades</p></div><div className='space-y-3'>{recentActivities.length ? recentActivities.map((item) => <div key={item.id} className='flex gap-3'><span className='mt-1 h-2.5 w-2.5 rounded-full bg-emerald-500 ring-4 ring-emerald-50'/><div><p className='text-sm font-semibold text-slate-800'>{item.title}</p><p className='text-xs text-slate-500'>{item.description}</p></div></div>) : <p className='text-sm text-slate-500'>As próximas atividades aparecerão aqui.</p>}</div></div>
      </aside>
    </div>

    <div className='rounded-[18px] border border-slate-200/80 bg-white p-4 shadow-[0_18px_45px_-36px_rgba(15,23,42,0.55)]'>
      <div className='grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto] lg:items-center'><label className='flex items-center gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500'><Search size={16}/> <input value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder='Buscar por nome ou ID da campanha...' className='w-full bg-transparent outline-none'/></label><div className='flex flex-wrap gap-2'>{statusFilters.map((filter) => <button key={filter.value} onClick={() => setStatusFilter(filter.value)} className={`rounded-full border px-3 py-2 text-xs font-semibold transition ${statusFilter === filter.value ? 'border-slate-950 bg-slate-950 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-emerald-200 hover:text-emerald-700'}`}>{filter.label}</button>)}</div></div>
      <div className='mt-3 flex flex-wrap gap-2 text-xs text-slate-500'><span className='inline-flex items-center gap-1 rounded-full bg-slate-50 px-3 py-1'><CalendarRange size={13}/>{periodFilter}</span><span className='inline-flex items-center gap-1 rounded-full bg-slate-50 px-3 py-1'><Filter size={13}/>{tagFilter}</span></div>
    </div>

    {loading ? <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>{Array.from({ length: 4 }).map((_, i) => <div key={i} className='h-56 animate-pulse rounded-[18px] border border-slate-200 bg-white/80'/>)}</div> : null}

    {!loading && filteredCampaigns.length === 0 ? (<CampaignCard><div className='relative overflow-hidden rounded-[18px] border border-dashed border-emerald-200 bg-emerald-50/40 p-10 text-center'><div className='mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[18px] bg-white shadow-sm'><Megaphone className='text-emerald-600'/></div><p className='text-lg font-semibold text-slate-800'>Nenhuma campanha encontrada.</p><p className='mx-auto mt-2 max-w-md text-sm text-slate-500'>Crie uma campanha ou ajuste os filtros para visualizar sua operação de mensagens.</p><button onClick={() => setShowCreate(true)} className='primary-button mt-5 inline-flex items-center gap-2'><Plus size={14}/>Criar primeira campanha</button></div></CampaignCard>) : null}

    {!loading && filteredCampaigns.length > 0 ? <div className='overflow-hidden rounded-[18px] border border-slate-200/80 bg-white shadow-[0_18px_45px_-36px_rgba(15,23,42,0.55)]'><div className='overflow-x-auto'><table className='min-w-[960px] w-full text-left text-sm'><thead className='bg-slate-50 text-xs uppercase tracking-[0.16em] text-slate-400'><tr><th className='px-5 py-4'>Campanha</th><th className='px-5 py-4'>Status</th><th className='px-5 py-4'>Enviados</th><th className='px-5 py-4'>Entregues</th><th className='px-5 py-4'>Lidos</th><th className='px-5 py-4'>Falhas</th><th className='px-5 py-4'>Progresso</th><th className='px-5 py-4'>Ações</th></tr></thead><tbody className='divide-y divide-slate-100'>{filteredCampaigns.map((c) => { const total = c.total_recipients || 0; const done = (c.total_sent || 0) + (c.total_failed || 0); const progress = total > 0 ? Number(((done / total) * 100).toFixed(1)) : 0; return <tr key={c.id} className='align-top transition hover:bg-slate-50/70'><td className='px-5 py-4'><p className='font-semibold text-slate-950'>{c.name}</p><p className='mt-1 text-xs text-slate-500'>ID: {c.id}</p><div className='mt-2 flex flex-wrap gap-1.5'><span className='rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700'>WhatsApp</span><span className='rounded-full bg-sky-50 px-2 py-1 text-[11px] font-semibold text-sky-700'>Segmento</span></div></td><td className='px-5 py-4'><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(c.status)}`}>{c.status}</span></td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(c.total_sent || 0)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(c.total_delivered || 0)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(c.total_read || 0)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(c.total_failed || 0)}</td><td className='px-5 py-4'><p className='mb-2 text-xs font-semibold text-slate-600'>{progress.toFixed(1)}%</p><div className='h-2 w-28 rounded-full bg-emerald-100'><div className='h-2 rounded-full bg-emerald-500' style={{ width: `${Math.min(progress, 100)}%` }}/></div></td><td className='px-5 py-4'><div className='flex flex-wrap gap-2'><button className='secondary-button inline-flex items-center gap-1'><BarChart3 size={13}/>Relatório</button>{c.status === 'draft' && <button onClick={() => void onStartCampaign(c.id)} className='primary-button'>Iniciar</button>}{c.status === 'running' && <button onClick={() => void onPauseCampaign(c.id)} className='secondary-button inline-flex items-center gap-1'><PauseCircle size={13}/>Pausar</button>}</div></td></tr>; })}</tbody></table></div></div> : null}


    {showCreate && <CampaignCreateModal><div className='space-y-3'>
      <h4 className='font-semibold'>Nova campanha</h4>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder='Nome da campanha' className='premium-input w-full' />
      {assetsLoading ? <div className='space-y-2'><div className='h-11 animate-pulse rounded-xl bg-slate-100'/><div className='h-11 animate-pulse rounded-xl bg-slate-100'/></div> : <>
        <select value={providerId} onChange={(e) => setProviderId(e.target.value)} className='premium-input w-full'>
          <option value=''>Selecione um provider conectado</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.display_name || p.provider_type} • {p.status}</option>)}
        </select>
        <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={!providerId || approvedTemplates.length === 0} className='premium-input w-full'>
          <option value=''>{approvedTemplates.length ? 'Selecione um template aprovado' : 'Nenhum template aprovado disponível'}</option>
          {approvedTemplates.map((t) => <option key={t.id} value={t.id}>{t.name} • {t.category || 'utility'} • approved</option>)}
        </select>
      </>}
      <div className='flex flex-wrap gap-2'>
        <span className={`rounded-full border px-3 py-1 text-xs ${badgeClass(providers.find((p) => p.id === providerId)?.status === 'connected')}`}>Provider {providers.find((p) => p.id === providerId)?.status || 'não selecionado'}</span>
        <span className={`rounded-full border px-3 py-1 text-xs ${badgeClass(!!selectedTemplate)}`}>Template {selectedTemplate ? 'approved' : 'pendente'}</span>
      </div>

      {!!templateVariables.length && <div className='rounded-xl border border-slate-200 bg-white p-3'>
        <p className='mb-3 text-sm font-semibold text-slate-900'>Mapeamento de variáveis</p>
        <div className='space-y-3'>
          {templateVariables.map((key) => (
            <div key={key} className='rounded-xl border border-slate-200 bg-slate-50 p-3'>
              <div className='mb-2 flex items-center gap-2'>
                <span className='rounded-full bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white'>Variável {key}</span>
                <span className='rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700'>Obrigatória</span>
              </div>
              <select value={variableMapping[key] || 'first_name'} onChange={(e) => setVariableMapping((prev) => ({ ...prev, [key]: e.target.value }))} className='premium-input w-full'>
                {VARIABLE_FIELD_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              {variableMapping[key] === FIXED_VALUE_FIELD && <input value={manualVariableValues[key] || ''} onChange={(e) => setManualVariableValues((prev) => ({ ...prev, [key]: e.target.value }))} placeholder='Exemplo: #4821' className='premium-input mt-2 w-full' />}
            </div>
          ))}
        </div>
      </div>}

      {selectedTemplate && <div className='rounded-xl border border-emerald-100 bg-emerald-50/40 p-3 text-sm text-slate-700'><p className='mb-1 font-semibold text-slate-900'>Preview do template</p><p className='whitespace-pre-wrap'>{renderPreview()}</p><p className='mt-2 text-xs text-slate-500'>Categoria: {selectedTemplate.category || 'utility'} • Idioma: {selectedTemplate.language}</p></div>}

      <div className='rounded-xl border border-slate-200 bg-slate-50 p-3'>
        <p className='mb-2 text-sm font-semibold'>Teste rápido</p>
        <div className='space-y-2'>
          <input value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder='Telefone' className='premium-input w-full' />
          {templateVariables.length > 0 && (
            <>
              <div className='space-y-1'>
                <label className='text-xs font-medium text-slate-600'>Variável 1</label>
                <input value={testVariableValues['1'] || ''} onChange={(e) => setTestVariableValues((prev) => ({ ...prev, ['1']: e.target.value }))} placeholder='Gabriel' className='premium-input w-full' />
              </div>
              <div className='space-y-1'>
                <label className='text-xs font-medium text-slate-600'>Variável 2</label>
                <input value={testVariableValues['2'] || ''} onChange={(e) => setTestVariableValues((prev) => ({ ...prev, ['2']: e.target.value }))} placeholder='#4821' className='premium-input w-full' />
              </div>
            </>
          )}
          {templateVariables.filter((key) => key !== '1' && key !== '2').map((key) => (
            <div key={`test-${key}`} className='space-y-1'>
              <label className='text-xs font-medium text-slate-600'>Variável {key}: valor de teste</label>
              <input value={testVariableValues[key] || ''} onChange={(e) => setTestVariableValues((prev) => ({ ...prev, [key]: e.target.value }))} placeholder={`Valor de teste da variável ${key}`} className='premium-input w-full' />
            </div>
          ))}
        </div>
        <button onClick={() => void onQuickTest()} disabled={!testPhone || !selectedTemplate || !providerId || hasVariableErrors || testSending} className='secondary-button mt-3 inline-flex items-center gap-2'>{testSending ? <Loader2 size={14} className='animate-spin'/> : <Send size={14}/> }Enviar teste</button>
        {testStatus && <p className={`mt-2 text-xs ${testStatus.type === 'success' ? 'text-emerald-600' : 'text-rose-600'}`}>{testStatus.message}</p>}
      </div>

      <div className='rounded-xl border border-slate-200 p-3'>
        <p className='mb-2 text-sm font-semibold'>Destinatários</p>
        <div className='mb-2 flex gap-2 text-xs'>
          <button type='button' onClick={() => setRecipientMode('csv')} className={`rounded border px-2 py-1 ${recipientMode === 'csv' ? 'bg-slate-900 text-white' : 'bg-white'}`}>CSV</button>
          <button type='button' onClick={() => { setRecipientMode('saved'); void reloadContacts(); }} className={`rounded border px-2 py-1 ${recipientMode === 'saved' ? 'bg-slate-900 text-white' : 'bg-white'}`}>Selecionar contatos salvos</button>
        </div>
        {recipientMode === 'csv' && <><p className='mb-2 text-xs text-slate-500'>CSV esperado: {csvHeaders.join(',')}</p>
        <textarea value={leadsText} onChange={(e) => setLeadsText(e.target.value)} rows={5} className='premium-input w-full' placeholder={`${csvHeaders.join(',')}
5516999999999,Gabriel,#4821`} />
        <label className='mt-2 block text-xs text-slate-500'>Upload CSV
          <input type='file' accept='.csv,text/csv' onChange={(e) => void onCsvUpload(e)} className='mt-1 block text-xs' />
        </label></>}

        {recipientMode === 'saved' && <div className='space-y-2'>
          <div className='flex gap-2'>
            <button type='button' onClick={() => void reloadContacts()} className='secondary-button whitespace-nowrap'>Recarregar contatos</button>
          </div>
          {contactsLoadError ? <p className='text-xs text-amber-600'>{contactsLoadError}</p> : null}
          <div className='text-xs text-gray-500'>
            contatos carregados: {savedContacts.length}
          </div>
          <div className='max-h-40 space-y-1 overflow-auto rounded border p-2'>
            {savedContacts.length === 0 ? <p className='text-xs text-slate-500'>Nenhum contato salvo ainda. Envie uma mensagem para o WhatsApp conectado ou importe via CSV.</p> : savedContacts.map((c) => (
              <label key={c.id} className='flex items-center gap-2 text-xs'>
                <input type='checkbox' checked={selectedContactIds.includes(c.id)} onChange={(e) => setSelectedContactIds((prev) => e.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id))} />
                <span>{c.name || c.phone} • {c.phone} • {c.source || 'whatsapp'}</span>
              </label>
            ))}
          </div>
        </div>}
      </div>

      {(hasCreateErrors || hasVariableErrors || hasRecipientVariableErrors) && <p className='text-xs text-amber-600'>Preencha nome, provider/template e todos os mapeamentos obrigatórios para continuar. Edite o contato em Contatos ou use valor fixo.</p>}
      <div className='flex justify-end gap-2'>
        <button onClick={() => setShowCreate(false)} className='secondary-button'>Cancelar</button>
        <button onClick={() => void onCreate()} disabled={hasCreateErrors || hasVariableErrors || hasRecipientVariableErrors || loading} className='primary-button inline-flex items-center gap-2'>
          {loading ? <Loader2 size={14} className='animate-spin'/> : null}Criar
        </button>
      </div>
    </div></CampaignCreateModal>}
  </div>;
}
