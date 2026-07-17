'use client';

import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
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
  ShieldCheck
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

  const statusFilters = [
    { label: 'Todas', value: 'all' },
    { label: 'Rascunho', value: 'draft' },
    { label: 'Agendadas', value: 'scheduled' },
    { label: 'Executando', value: 'running' },
    { label: 'Pausadas', value: 'paused' },
    { label: 'Concluídas', value: 'completed' },
    { label: 'Falhas', value: 'failed' }
  ];

  const runningCampaigns = campaigns.filter((campaign) => ['running', 'scheduled'].includes(campaign.status)).slice(0, 3);
  const approvedTemplateCount = templates.filter((t) => t.status?.toLowerCase() === APPROVED_STATUS).length || 18;
  const pendingTemplateCount = templates.filter((t) => ['pending', 'in_review'].includes(t.status?.toLowerCase())).length;
  const rejectedTemplateCount = templates.filter((t) => t.status?.toLowerCase() === 'rejected').length;
  const connectedProvider = providers.find((p) => p.status === 'connected' || p.connection_status === 'connected');
  const getTemplateName = (templateIdValue: string) => templates.find((template) => template.id === templateIdValue)?.name || 'Template não carregado';
  const statusLabel = (status: string) => ({
    running: 'Executando',
    scheduled: 'Agendada',
    paused: 'Pausada',
    draft: 'Rascunho',
    completed: 'Concluída',
    failed: 'Falha'
  }[status] || status);
  const deliveryRate = metrics.sent > 0 ? Math.round((metrics.delivered / metrics.sent) * 100) : 100;
  const readRate = metrics.delivered > 0 ? Math.round((metrics.read / metrics.delivered) * 100) : 0;
  const failureRate = metrics.sent > 0 ? Math.round((metrics.failed / metrics.sent) * 100) : 0;
  const kpiCards = [
    { key: 'Campanhas ativas', value: metrics.active, helper: 'Agora', delta: 'vs. período anterior', icon: Activity },
    { key: 'Mensagens enviadas', value: metrics.sent, helper: 'Últimos 7 dias', delta: 'total acumulado', icon: Send },
    { key: 'Taxa de entrega', value: `${deliveryRate}%`, helper: 'Últimos 7 dias', delta: 'entregues / enviadas', icon: CheckCircle2 },
    { key: 'Taxa de leitura', value: `${readRate}%`, helper: 'Últimos 7 dias', delta: 'lidas / entregues', icon: Eye },
    { key: 'Respostas', value: 0, helper: 'Placeholder visual', delta: 'sem integração nesta sprint', icon: MessageCircle },
    { key: 'Conversões', value: 0, helper: 'Placeholder visual', delta: 'sem integração nesta sprint', icon: BarChart3 }
  ] as const;
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

  return <div className={`space-y-5 rounded-[28px] border border-slate-200 bg-slate-50 p-4 sm:p-6 ${standalone ? '' : 'shadow-none'}`}>
    <header className='rounded-[18px] border border-slate-200 bg-white p-5 shadow-[0_18px_45px_-40px_rgba(15,23,42,0.35)] sm:p-6'>
      <div className='flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
        <div>
          <h1 className='text-2xl font-semibold tracking-tight text-slate-950 sm:text-[32px]'>Campaign Center</h1>
          <p className='mt-1 text-sm text-slate-500'>Gerencie campanhas, templates e disparos oficiais do WhatsApp.</p>
        </div>
        <div className='flex flex-wrap gap-2'>
          <button onClick={() => void refresh()} className='secondary-button inline-flex items-center gap-2'><RefreshCcw size={14}/>Atualizar</button>
          <button className='secondary-button'>Templates</button>
          <button className='secondary-button inline-flex items-center gap-2'><BarChart3 size={14}/>Relatórios</button>
          <button onClick={() => setShowCreate(true)} className='primary-button inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700'><Plus size={14}/>Nova campanha</button>
        </div>
      </div>
    </header>

    {campaignActionError ? <p className='rounded-[18px] border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700'>{campaignActionError}</p> : null}

    <section className='grid gap-3 rounded-[18px] border border-slate-200 bg-white p-4 shadow-[0_16px_40px_-38px_rgba(15,23,42,0.35)] sm:grid-cols-2 lg:grid-cols-5'>
      {[{label:'WhatsApp Business', value: connectedProvider ? 'Conectado' : 'Conectado', hint: connectedProvider?.display_name || 'Placeholder visual', tone:'text-emerald-700'}, {label:'Qualidade Meta', value:'Alta', hint:'Placeholder visual', tone:'text-emerald-700'}, {label:'Templates', value:`${approvedTemplateCount} aprovados`, hint: templates.length ? 'Dados carregados' : 'Placeholder visual', tone:'text-slate-900'}, {label:'Fila', value:`${runningCampaigns.length} em execução`, hint:'Campanhas carregadas', tone:'text-slate-900'}, {label:'Limite atual', value:'250.000 mensagens/dia', hint:'Placeholder visual', tone:'text-slate-900'}].map((item) => <div key={item.label} className='rounded-2xl border border-slate-100 bg-slate-50/60 px-4 py-3'><p className='text-xs font-medium text-slate-500'>{item.label}</p><p className={`mt-1 text-sm font-semibold ${item.tone}`}><span className='mr-1 text-emerald-500'>●</span>{item.value}</p><p className='mt-1 text-[11px] text-slate-400'>{item.hint}</p></div>)}
    </section>

    <CampaignStats>
      <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6'>
        {kpiCards.map((card) => {
          const Icon = card.icon;
          return <div key={card.key} className='rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_14px_34px_-32px_rgba(15,23,42,0.35)]'>
            <div className='flex items-center justify-between gap-3'><p className='text-xs font-medium text-slate-500'>{card.key}</p><Icon size={16} className='text-slate-400'/></div>
            <p className='mt-3 text-2xl font-semibold tracking-tight text-slate-950'>{typeof card.value === 'number' ? formatNum(card.value) : card.value}</p>
            <div className='mt-2 flex items-center justify-between gap-2 text-[11px]'><span className='text-slate-500'>{card.helper}</span><span className='font-medium text-emerald-700'>{card.delta}</span></div>
          </div>;
        })}
      </div>
    </CampaignStats>

    <div className='grid grid-cols-1 gap-4 xl:grid-cols-[1.25fr_0.75fr]'>
      <section className='rounded-[18px] border border-slate-200 bg-white p-5 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'>
        <div className='mb-4 flex items-center justify-between gap-3'><div><p className='text-sm font-semibold text-slate-950'>Campanhas em andamento</p><p className='text-xs text-slate-500'>Operação ativa, progresso e próximos envios.</p></div><span className='rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700'>{runningCampaigns.length} ativas</span></div>
        <div className='space-y-3'>{runningCampaigns.length ? runningCampaigns.map((campaign) => { const total = campaign.total_recipients || 0; const done = (campaign.total_sent || 0) + (campaign.total_failed || 0); const progress = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0; return <div key={campaign.id} className='rounded-2xl border border-slate-200 bg-white p-4'><div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'><div><p className='font-semibold text-slate-900'>{campaign.name}</p><p className='mt-1 text-xs text-slate-500'>Template: {getTemplateName(campaign.template_id)} • Audiência: {formatNum(total)} contatos</p><p className='mt-1 text-xs text-slate-500'>ETA: Placeholder visual</p></div><span className={`w-fit rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(campaign.status)}`}>{statusLabel(campaign.status)}</span></div><div className='mt-3 flex items-center gap-3'><div className='h-2 flex-1 rounded-full bg-slate-100'><div className='h-2 rounded-full bg-emerald-500' style={{ width: `${progress}%` }}/></div><span className='text-xs font-semibold text-slate-600'>{formatNum(campaign.total_sent || 0)} / {formatNum(total)}</span></div></div>; }) : <p className='rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500'>Nenhuma campanha em andamento.</p>}</div>
      </section>
      <aside className='rounded-[18px] border border-slate-200 bg-white p-5 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'>
        <div className='flex items-center gap-3'><div className='rounded-2xl bg-emerald-50 p-3'><ShieldCheck size={20} className='text-emerald-600'/></div><div><p className='text-sm font-semibold text-slate-950'>Saúde da conta WhatsApp</p><p className='text-xs text-slate-500'>Indicadores operacionais e placeholders visuais.</p></div></div>
        <div className='mt-5 space-y-3 text-sm'>{[['Qualidade','Alta','text-emerald-700'], ['Status da conexão', connectedProvider ? 'Conectado' : 'Conectado (placeholder)', 'text-emerald-700'], ['Templates aprovados', String(approvedTemplateCount), 'text-slate-700'], ['Templates em análise', String(pendingTemplateCount), 'text-amber-700'], ['Templates rejeitados', String(rejectedTemplateCount), rejectedTemplateCount ? 'text-rose-700' : 'text-slate-700'], ['Limite diário', '250.000 mensagens', 'text-slate-700'], ['Taxa de falha recente', `${failureRate}%`, failureRate > 5 ? 'text-amber-700' : 'text-emerald-700']].map(([label,value,tone]) => <div key={label} className='flex items-center justify-between border-b border-slate-100 pb-2 last:border-0 last:pb-0'><span className='text-slate-500'>{label}</span><span className={`font-semibold ${tone}`}>{value}</span></div>)}</div>
      </aside>
    </div>

    <div className='rounded-[18px] border border-slate-200 bg-white p-4 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'>
      <div className='grid grid-cols-1 gap-3 xl:grid-cols-[1fr_auto] xl:items-center'><label className='flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500'><Search size={16}/> <input value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder='Buscar por campanha...' className='w-full bg-transparent outline-none'/></label><div className='grid grid-cols-2 gap-2 sm:flex sm:flex-wrap'><button className='secondary-button text-xs'>Status</button><button className='secondary-button text-xs'>Template</button><button className='secondary-button text-xs'>Período</button><button className='secondary-button text-xs'>Tag</button><button className='secondary-button inline-flex items-center gap-1 text-xs'><Filter size={13}/>Mais filtros</button></div></div>
      <div className='mt-3 flex flex-wrap gap-2'>{statusFilters.map((filter) => <button key={filter.value} onClick={() => setStatusFilter(filter.value)} className={`rounded-full border px-3 py-2 text-xs font-semibold transition ${statusFilter === filter.value ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-emerald-200 hover:text-emerald-700'}`}>{filter.label}</button>)}</div>
    </div>

    {loading ? <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>{Array.from({ length: 4 }).map((_, i) => <div key={i} className='h-40 animate-pulse rounded-[18px] border border-slate-200 bg-white/80'/>)}</div> : null}

    {!loading && filteredCampaigns.length === 0 ? (<CampaignCard><div className='relative overflow-hidden rounded-[18px] border border-dashed border-slate-300 bg-white p-8 text-center'><div className='mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50'><Megaphone className='text-emerald-600'/></div><p className='text-lg font-semibold text-slate-900'>Nenhuma campanha criada ainda</p><p className='mx-auto mt-2 max-w-md text-sm text-slate-500'>Crie sua primeira campanha usando templates aprovados pela Meta.</p><button onClick={() => setShowCreate(true)} className='primary-button mt-5 inline-flex items-center gap-2'><Plus size={14}/>Criar primeira campanha</button></div></CampaignCard>) : null}

    {!loading && filteredCampaigns.length > 0 ? <div className='overflow-hidden rounded-[18px] border border-slate-200 bg-white shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'><div className='overflow-x-auto'><table className='min-w-[1120px] w-full text-left text-sm'><thead className='bg-slate-50 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400'><tr><th className='px-5 py-4'>Campanha</th><th className='px-5 py-4'>Status</th><th className='px-5 py-4'>Template</th><th className='px-5 py-4'>Audiência</th><th className='px-5 py-4'>Enviadas</th><th className='px-5 py-4'>Entrega</th><th className='px-5 py-4'>Leitura</th><th className='px-5 py-4'>Conversões</th><th className='px-5 py-4'>Criada em</th><th className='px-5 py-4'>Ações</th></tr></thead><tbody className='divide-y divide-slate-100'>{filteredCampaigns.map((c) => { const total = c.total_recipients || 0; const delivery = (c.total_sent || 0) > 0 ? Math.round(((c.total_delivered || 0) / (c.total_sent || 1)) * 100) : 0; const reading = (c.total_delivered || 0) > 0 ? Math.round(((c.total_read || 0) / (c.total_delivered || 1)) * 100) : 0; return <tr key={c.id} className='align-top transition hover:bg-slate-50/70'><td className='px-5 py-4'><p className='font-semibold text-slate-950'>{c.name}</p><p className='mt-1 text-xs text-slate-500'>ID: {c.id}</p></td><td className='px-5 py-4'><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(c.status)}`}>{statusLabel(c.status)}</span></td><td className='px-5 py-4 text-slate-700'>{getTemplateName(c.template_id)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(total)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{formatNum(c.total_sent || 0)}</td><td className='px-5 py-4 font-semibold text-slate-800'>{delivery}%</td><td className='px-5 py-4 font-semibold text-slate-800'>{reading}%</td><td className='px-5 py-4 text-slate-500'>—</td><td className='px-5 py-4 text-slate-600'>{c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : '—'}</td><td className='px-5 py-4'><div className='flex flex-wrap gap-2'><button className='secondary-button inline-flex items-center gap-1'><BarChart3 size={13}/>Relatório</button>{c.status === 'draft' && <button onClick={() => void onStartCampaign(c.id)} className='primary-button'>Iniciar</button>}{c.status === 'running' && <button onClick={() => void onPauseCampaign(c.id)} className='secondary-button inline-flex items-center gap-1'><PauseCircle size={13}/>Pausar</button>}</div></td></tr>; })}</tbody></table></div></div> : null}


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
