'use client';

import { ChangeEvent, Fragment, memo, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Copy,
  Eye,
  Filter,
  Loader2,
  Megaphone,
  MessageCircle,
  FileText,
  PauseCircle,
  Plus,
  RefreshCcw,
  Search,
  Send,
  ShieldCheck,
  X
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
  syncTemplates,
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
  const regex = /\{\{\s*([^}]+?)\s*\}\}/g;
  const variables = new Set<string>();
  let match = regex.exec(text);

  while (match) {
    variables.add(match[1].trim());
    match = regex.exec(text);
  }

  return Array.from(variables).sort((a, b) => Number(a) - Number(b));
}


function normalizeTemplateStatus(status?: string | null) {
  return String(status || 'unknown').toLowerCase();
}

function statusLabel(status: string) {
  return ({
    approved: 'Approved',
    pending: 'Pending',
    rejected: 'Rejected',
    paused: 'Paused',
    disabled: 'Disabled',
    running: 'Executando',
    scheduled: 'Agendada',
    draft: 'Rascunho',
    completed: 'Concluída',
    failed: 'Falha'
  } as Record<string, string>)[String(status || '').toLowerCase()] || status || '—';
}

const TemplateStatusBadge = memo(function TemplateStatusBadge({ status }: { status?: string | null }) {
  const tone = ({
    approved: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    pending: 'border-orange-200 bg-orange-50 text-orange-700',
    rejected: 'border-rose-200 bg-rose-50 text-rose-700',
    paused: 'border-slate-200 bg-slate-100 text-slate-600',
    disabled: 'border-slate-300 bg-slate-200 text-slate-800'
  } as Record<string, string>)[normalizeTemplateStatus(status)] || 'border-slate-200 bg-slate-50 text-slate-600';
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tone}`}>{statusLabel(status || '')}</span>;
});

const TemplateQualityBadge = memo(function TemplateQualityBadge({ value }: { value?: string | null }) {
  const normalized = String(value || 'unknown').toLowerCase();
  const label = normalized.includes('high') || normalized.includes('alta') ? 'Alta' : normalized.includes('medium') || normalized.includes('média') || normalized.includes('media') ? 'Média' : normalized.includes('low') || normalized.includes('baixa') ? 'Baixa' : 'Desconhecida';
  const dot = label === 'Alta' ? 'bg-emerald-500' : label === 'Média' ? 'bg-amber-500' : label === 'Baixa' ? 'bg-rose-500' : 'bg-slate-300';
  return <span className='inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700'><span className={`h-2 w-2 rounded-full ${dot}`} />{label}</span>;
});

function getTemplateComponents(template?: WhatsAppTemplate | null): Array<Record<string, any>> {
  if (!template) return [];
  const direct = Array.isArray(template.components) ? template.components : [];
  const raw = template.metadata_json;
  const metadata = typeof raw === 'string' ? (() => { try { return JSON.parse(raw); } catch { return {}; } })() : raw && typeof raw === 'object' ? raw : {};
  const nested = Array.isArray((metadata as any).components) ? (metadata as any).components : [];
  return direct.length ? direct : nested;
}

function renderWithVariables(text: string, values: Record<string, string>) {
  const parts = text.split(/(\{\{\s*[^}]+\s*\}\})/g);
  return parts.map((part, index) => {
    const match = part.match(/\{\{\s*([^}]+?)\s*\}\}/);
    if (!match) return <Fragment key={index}>{part}</Fragment>;
    const key = match[1].trim();
    return <mark key={index} className='rounded-md bg-emerald-100 px-1 font-semibold text-emerald-800'>{values[key] || part}</mark>;
  });
}

function getAllTemplateText(template: WhatsAppTemplate) {
  const components = getTemplateComponents(template);
  return [template.name, template.category, template.language, getTemplateText(template), ...components.map((c) => `${c.type || ''} ${c.text || ''} ${JSON.stringify(c.buttons || c.example || '')}`)].join(' ');
}

const TemplatePreview = memo(function TemplatePreview({ template, onClose }: { template: WhatsAppTemplate; onClose: () => void }) {
  const components = getTemplateComponents(template);
  const text = getTemplateText(template);
  const variables = useMemo(() => Array.from(new Set([...extractVariables(text), ...Array.from(text.matchAll(/\{\{\s*([^}\d][^}]*)\s*\}\}/g)).map((m) => m[1].trim())])), [text]);
  const [values, setValues] = useState<Record<string, string>>({});
  const byType = (type: string) => components.filter((c) => String(c.type || '').toUpperCase() === type);
  const header = byType('HEADER')[0];
  const body = byType('BODY')[0];
  const footer = byType('FOOTER')[0];
  const buttons = byType('BUTTONS').flatMap((c) => Array.isArray(c.buttons) ? c.buttons : []);
  const headerFormat = String(header?.format || '').toUpperCase();
  return <aside className='fixed inset-y-0 right-0 z-[70] flex w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl'>
    <div className='flex items-center justify-between border-b border-slate-100 px-6 py-4'><div><p className='text-lg font-semibold text-slate-950'>{template.name}</p><p className='text-xs text-slate-500'>{template.category || '—'} • {template.language || '—'}</p></div><button onClick={onClose} className='secondary-button'>Fechar</button></div>
    <div className='grid flex-1 gap-4 overflow-auto p-6 lg:grid-cols-[1fr_220px]'>
      <div className='rounded-[28px] bg-[#efeae2] p-4 shadow-inner'><div className='rounded-2xl bg-[#dcf8c6] p-4 text-sm leading-relaxed text-slate-800 shadow-sm'>
        {header ? <div className='mb-3 font-bold'>{headerFormat === 'IMAGE' ? <span>Imagem: {String(header.example?.header_handle?.[0] || header.example || '')}</span> : headerFormat === 'VIDEO' ? <span>Vídeo: {String(header.example?.header_handle?.[0] || header.example || '')}</span> : headerFormat === 'DOCUMENT' ? <span>Documento: {String(header.example?.header_handle?.[0] || header.example || '')}</span> : renderWithVariables(String(header.text || ''), values)}</div> : null}
        <div className='whitespace-pre-wrap'>{renderWithVariables(String(body?.text || text || ''), values)}</div>
        {footer?.text ? <div className='mt-3 text-xs text-slate-500'>{renderWithVariables(String(footer.text), values)}</div> : null}
        {buttons.length ? <div className='mt-3 space-y-2 border-t border-emerald-200 pt-2'>{buttons.map((button, index) => <div key={index} className='rounded-lg bg-white/80 px-3 py-2 text-center text-xs font-semibold text-sky-700'>{String(button.type || '').replace('_', ' ')} · {button.text || button.url || button.phone_number}</div>)}</div> : null}
      </div></div>
      <div className='space-y-3'><p className='text-sm font-semibold text-slate-950'>Simulação de variáveis</p>{variables.length ? variables.map((key) => <label key={key} className='block text-xs font-medium text-slate-600'><span>{`{{${key}}}`}</span><input value={values[key] || ''} onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))} className='premium-input mt-1 w-full' placeholder={key === '1' ? 'Gabriel' : key === '2' ? '#4521' : key} /></label>) : <p className='text-xs text-slate-500'>Este template não possui variáveis.</p>}</div>
    </div>
  </aside>;
});

type CampaignsTabProps = {
  standalone?: boolean;
};

export default function CampaignsTab({ standalone = false }: CampaignsTabProps) {
  const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [showReports, setShowReports] = useState(false);
  const [previewTemplate, setPreviewTemplate] = useState<WhatsAppTemplate | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [syncingTemplates, setSyncingTemplates] = useState(false);
  const [creatingCampaign, setCreatingCampaign] = useState(false);
  const [wizardStep, setWizardStep] = useState(1);
  const [campaignObjective, setCampaignObjective] = useState('Promoção');
  const [sendMode, setSendMode] = useState<'draft' | 'now' | 'schedule'>('draft');
  const [scheduledAt, setScheduledAt] = useState('');
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
  const [periodFilter, setPeriodFilter] = useState('all');
  const [tagFilter, setTagFilter] = useState('all');
  const [templateFilter, setTemplateFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [templateStatusFilter, setTemplateStatusFilter] = useState('all');
  const [templateCategoryFilter, setTemplateCategoryFilter] = useState('all');
  const [templateLanguageFilter, setTemplateLanguageFilter] = useState('all');
  const [templateQualityFilter, setTemplateQualityFilter] = useState('all');
  const [templateSearchTerm, setTemplateSearchTerm] = useState('');
  const [lastTemplateSyncAt, setLastTemplateSyncAt] = useState<string | null>(null);

  function getTemplateName(templateIdValue: string) {
    return templates.find((template) => template.id === templateIdValue)?.name || 'Template não carregado';
  }

  const filteredCampaigns = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase();
    return campaigns.filter((c) => {
      const templateName = getTemplateName(c.template_id);
      const tags = Array.isArray(c.metadata_json?.tags) ? c.metadata_json.tags.join(' ') : '';
      const responsible = String(c.metadata_json?.responsible || '');
      const matchesSearch = !needle || `${c.name} ${c.id} ${templateName} ${tags} ${responsible}`.toLowerCase().includes(needle);
      const matchesStatus = statusFilter === 'all' || c.status === statusFilter;
      const matchesTemplate = templateFilter === 'all' || c.template_id === templateFilter;
      return matchesSearch && matchesStatus && matchesTemplate;
    });
  }, [campaigns, searchTerm, statusFilter, templateFilter, templates]);

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
  const refresh = async (showFeedback = false) => {
    if (refreshing) return;
    setRefreshing(true);
    setLoading(true);
    try {
      const [campaignData, providerData, templateData] = await Promise.all([listWhatsAppCampaigns(), listWhatsAppProviders(), listTemplates()]);
      setCampaigns(campaignData);
      setProviders(providerData);
      setTemplates(templateData);
      try {
        await fetchContacts();
      } catch (error) {
        console.error('[CAMPAIGNS CONTACTS LOAD ERROR]', error);
        setSavedContacts([]);
        setContactsLoadError('Não foi possível carregar contatos');
      }
      if (showFeedback) {
        setToast({ type: 'success', message: 'Campaign Center atualizado.' });
      }
    } catch (error) {
      setToast({ type: 'error', message: (error as Error).message || 'Falha ao atualizar campanhas.' });
    } finally {
      setLoading(false);
      setRefreshing(false);
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
    if (!toast) return undefined;

    const timeout = window.setTimeout(() => {
      setToast(null);
    }, 3500);

    return () => window.clearTimeout(timeout);
  }, [toast]);

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
  const approvedTemplateCount = templates.filter((t) => t.status?.toLowerCase() === APPROVED_STATUS).length;
  const connectedProvider = providers.find((p) => p.status === 'connected' || p.connection_status === 'connected');
  const deliveryRate = metrics.sent > 0 ? Math.round((metrics.delivered / metrics.sent) * 100) : null;
  const readRate = metrics.delivered > 0 ? Math.round((metrics.read / metrics.delivered) * 100) : 0;
  const failureRate = metrics.sent > 0 ? Math.round((metrics.failed / metrics.sent) * 100) : 0;

  const templateStatuses = ['all', ...Array.from(new Set(templates.map((t) => String(t.status || '').toLowerCase()).filter(Boolean)))];
  const templateCategories = ['all', ...Array.from(new Set(templates.map((t) => String(t.category || '').toLowerCase()).filter(Boolean)))];
  const templateLanguages = ['all', ...Array.from(new Set(templates.map((t) => String(t.language || '')).filter(Boolean)))];
  const filteredTemplates = useMemo(() => templates.filter((template) => {
    const needle = templateSearchTerm.trim().toLowerCase();
    const quality = String(template.quality_rating || template.quality_score || 'unknown').toLowerCase();
    const matchesSearch = !needle || getAllTemplateText(template).toLowerCase().includes(needle);
    const matchesStatus = templateStatusFilter === 'all' || String(template.status || '').toLowerCase() === templateStatusFilter;
    const matchesCategory = templateCategoryFilter === 'all' || String(template.category || '').toLowerCase() === templateCategoryFilter;
    const matchesLanguage = templateLanguageFilter === 'all' || String(template.language || '') === templateLanguageFilter;
    const matchesQuality = templateQualityFilter === 'all' || quality.includes(templateQualityFilter);
    return matchesSearch && matchesStatus && matchesCategory && matchesLanguage && matchesQuality;
  }), [templates, templateSearchTerm, templateStatusFilter, templateCategoryFilter, templateLanguageFilter, templateQualityFilter]);

  const onSyncTemplates = async () => {
    if (syncingTemplates) return;
    setSyncingTemplates(true);
    try {
      const before = new Set(templates.map((template) => template.id));
      await syncTemplates();
      const templateData = await listTemplates();
      const updatedCount = templateData.filter((template) => !before.has(template.id)).length;
      setTemplates(templateData);
      setLastTemplateSyncAt(new Date().toISOString());
      setToast({ type: 'success', message: updatedCount > 0 ? `${updatedCount} template${updatedCount > 1 ? 's' : ''} atualizado${updatedCount > 1 ? 's' : ''}.` : 'Nenhum template novo encontrado.' });
    } catch (error) {
      setToast({ type: 'error', message: (error as Error).message || 'Falha ao sincronizar templates.' });
    } finally {
      setSyncingTemplates(false);
    }
  };

  const kpiCards = [
    { key: 'Campanhas ativas', value: metrics.active, indicator: 'Agora', icon: Activity },
    { key: 'Mensagens enviadas', value: metrics.sent, indicator: 'Hoje', icon: Send },
    { key: 'Taxa de entrega', value: deliveryRate === null ? '—' : `${deliveryRate}%`, indicator: deliveryRate === null ? 'Em breve' : 'Hoje', icon: CheckCircle2 },
    { key: 'Taxa de leitura', value: metrics.delivered > 0 ? `${readRate}%` : '—', indicator: metrics.delivered > 0 ? 'Hoje' : 'Em breve', icon: Eye },
    { key: 'Respostas', value: '—', indicator: 'Em breve', icon: MessageCircle },
    { key: 'Conversões', value: '—', indicator: 'Em breve', icon: BarChart3 }
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
    if (!name || !providerId || !templateId || hasRecipientVariableErrors || creatingCampaign) return;
    if (sendMode === 'schedule' && (!scheduledAt || new Date(scheduledAt) <= new Date())) { setToast({ type: 'error', message: 'Escolha um horário futuro para agendar.' }); return; }
    const recipientsCount = recipientMode === 'csv' ? parseLeads().length : selectedContactIds.length;
    if (sendMode !== 'draft' && recipientsCount === 0) { setToast({ type: 'error', message: 'Audiência vazia. Adicione destinatários antes do envio.' }); return; }
    setCreatingCampaign(true);
    try {
    const created = await createWhatsAppCampaign({ name, provider_id: providerId, template_id: templateId, status: sendMode === 'schedule' ? 'scheduled' : 'draft', scheduled_at: sendMode === 'schedule' ? scheduledAt : null, metadata_json: { objective: campaignObjective } });
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
    if (sendMode === 'now') await startWhatsAppCampaign(created.id);
    setToast({ type: 'success', message: sendMode === 'draft' ? 'Rascunho criado.' : sendMode === 'schedule' ? 'Campanha agendada.' : 'Campanha criada e iniciada.' });
    await refresh();
    } catch (error) {
      setToast({ type: 'error', message: (error as Error).message || 'Falha ao criar campanha.' });
    } finally {
      setCreatingCampaign(false);
    }
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

  const hasCreateErrors = !name || !providerId || !templateId || (sendMode === 'schedule' && (!scheduledAt || new Date(scheduledAt) <= new Date()));
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

  return <div className={`space-y-4 rounded-[24px] border border-slate-200 bg-slate-50 p-3 sm:p-4 ${standalone ? '' : 'shadow-none'}`}>
    <header className='rounded-[18px] border border-slate-200 bg-white px-4 py-3 shadow-[0_14px_35px_-34px_rgba(15,23,42,0.35)] sm:px-5'>
      <div className='flex min-h-[64px] flex-col gap-3 lg:flex-row lg:items-center lg:justify-between'>
        <div>
          <h1 className='text-[22px] font-semibold tracking-tight text-slate-950 sm:text-2xl'>Campaign Center</h1>
          <p className='mt-0.5 text-xs text-slate-500 sm:text-sm'>Gerencie campanhas, templates e disparos oficiais do WhatsApp.</p>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <button onClick={() => void refresh(true)} disabled={refreshing} className='secondary-button inline-flex h-9 items-center gap-2 px-3 text-xs'>{refreshing ? <Loader2 size={14} className='animate-spin'/> : <RefreshCcw size={14}/>}Atualizar</button>
          <button onClick={() => { setShowTemplates(true); void loadAssets(); }} className='secondary-button inline-flex h-9 items-center border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700 hover:border-emerald-300'>Templates</button>
          <button onClick={() => setShowReports(true)} className='secondary-button inline-flex h-9 items-center gap-2 px-3 text-xs'><BarChart3 size={14}/>Relatórios</button>
          <button onClick={() => setShowCreate(true)} className='primary-button inline-flex h-9 items-center gap-2 bg-emerald-600 px-3 text-xs font-semibold shadow-sm hover:bg-emerald-700'><Plus size={14}/>Nova campanha</button>
        </div>
      </div>
    </header>

    {toast ? <div className='pointer-events-none fixed right-5 top-5 z-50'>
      <div className={`pointer-events-auto flex max-w-sm items-start gap-3 rounded-[14px] border bg-white px-4 py-3 text-xs font-medium shadow-[0_18px_45px_-28px_rgba(15,23,42,0.45)] ${toast.type === 'success' ? 'border-emerald-200 text-emerald-700' : 'border-rose-200 text-rose-700'}`}>
        <span>{toast.message}</span>
        <button type='button' onClick={() => setToast(null)} className='-mr-1 rounded-full p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600' aria-label='Fechar aviso'>
          <X size={12} />
        </button>
      </div>
    </div> : null}

    {campaignActionError ? <p className='rounded-[18px] border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700'>{campaignActionError}</p> : null}

    <section className='rounded-[18px] border border-slate-200 bg-white px-3 py-2 shadow-[0_12px_32px_-34px_rgba(15,23,42,0.35)]'>
      <div className='flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-600'>
        {[`WhatsApp ${connectedProvider ? 'conectado' : '—'}`, 'Qualidade: —', `${approvedTemplateCount} templates`, `${runningCampaigns.length} em execução`, 'Limite: —'].map((item, index) => <span key={item} className='inline-flex items-center gap-1.5 whitespace-nowrap font-medium'><span className={connectedProvider && index === 0 ? 'text-emerald-500' : 'text-slate-300'}>●</span>{item}</span>)}
      </div>
    </section>

    <section className='rounded-[18px] border border-slate-200 bg-white px-4 py-3 shadow-[0_12px_32px_-34px_rgba(15,23,42,0.35)]'>
      <div className='mb-2 flex items-center justify-between gap-3'><p className='text-sm font-semibold text-slate-950'>Últimas atividades</p><span className='text-[11px] font-medium text-slate-400'>Status</span></div>
      <div className='rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-center'><Activity className='mx-auto mb-2 text-slate-300' size={22}/><p className='font-semibold text-slate-900'>Nenhuma atividade</p></div>
    </section>

    <CampaignStats>
      <div className='grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6'>
        {kpiCards.map((card) => {
          const Icon = card.icon;
          return <div key={card.key} className='rounded-[16px] border border-slate-200 bg-white px-3 py-3 shadow-[0_14px_34px_-32px_rgba(15,23,42,0.35)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-28px_rgba(15,23,42,0.35)]'>
            <div className='flex items-center justify-between gap-3'><p className='text-xs font-medium text-slate-500'>{card.key}</p><Icon size={16} className='text-slate-400'/></div>
            <p className='mt-2 text-xl font-bold tracking-tight text-slate-950'>{typeof card.value === 'number' ? formatNum(card.value) : card.value}</p>
            <p className={`mt-1 flex items-center gap-1 text-[11px] font-normal ${card.indicator === 'Em breve' ? 'text-slate-400' : 'text-emerald-700'}`}>{card.indicator === 'Em breve' ? null : <span className='text-[10px] leading-none'>●</span>}{card.indicator}</p>
          </div>;
        })}
      </div>
    </CampaignStats>

    <div className='grid grid-cols-1 gap-3 xl:grid-cols-[1fr_0.9fr]'>
      <section className='rounded-[18px] border border-slate-200 bg-white px-4 py-3 shadow-[0_12px_32px_-34px_rgba(15,23,42,0.35)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-30px_rgba(15,23,42,0.35)]'>
        <p className='text-sm font-semibold text-slate-950'>Fila de campanhas</p>
        <div className='my-3 h-px bg-slate-100'/>
        <div className='flex items-start gap-2'>
          <CheckCircle2 size={16} className={runningCampaigns.length ? 'mt-0.5 text-emerald-600' : 'mt-0.5 text-slate-400'}/>
          <div>
            <p className='text-sm font-semibold text-slate-800'>{runningCampaigns.length ? `${runningCampaigns.length} campanha${runningCampaigns.length > 1 ? 's' : ''} em execução` : 'Nenhuma campanha em execução'}</p>
            <p className='mt-0.5 text-xs font-normal text-slate-500'>{runningCampaigns.length ? 'Envios em andamento.' : 'Operação aguardando novos envios.'}</p>
          </div>
        </div>
      </section>
      <aside className='rounded-[18px] border border-slate-200 bg-white px-4 py-3 shadow-[0_12px_32px_-34px_rgba(15,23,42,0.35)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-30px_rgba(15,23,42,0.35)]'>
        <div className='mb-3 flex items-center gap-2'><ShieldCheck size={16} className='text-emerald-600'/><p className='text-sm font-semibold text-slate-950'>Saúde da conta</p></div>
        <div className='grid grid-cols-[minmax(92px,1fr)_auto] gap-x-4 gap-y-2 text-xs'>{[['Qualidade','—','text-slate-500'], ['Status', connectedProvider ? 'Conectado' : '—', connectedProvider ? 'text-emerald-700' : 'text-slate-500'], ['Templates', String(approvedTemplateCount), 'text-slate-700'], ['Falhas', metrics.sent > 0 ? `${failureRate}%` : '—', failureRate > 5 ? 'text-amber-700' : 'text-slate-500'], ['Limite', '—', 'text-slate-500']].map(([label,value,tone]) => <Fragment key={label}><p className='text-slate-500'>{label}</p><p className={`text-right font-bold ${tone}`}>{value}</p></Fragment>)}</div>
      </aside>
    </div>

    <div className='rounded-[18px] border border-slate-200 bg-white p-3 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'>
      <div className='grid grid-cols-1 gap-3 xl:grid-cols-[minmax(320px,0.78fr)_auto] xl:items-center'><label className='flex h-10 items-center gap-3 rounded-full border border-slate-200 bg-white px-3 text-sm text-slate-500 transition duration-200 focus-within:border-emerald-300 focus-within:shadow-[0_0_0_4px_rgba(16,185,129,0.10)]'><Search size={16}/> <input value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder='Buscar campanhas...' className='w-full bg-transparent outline-none'/></label><div className='grid grid-cols-2 gap-2 sm:flex sm:flex-wrap'><select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className='premium-input h-9 text-xs'><option value='all'>Status</option>{statusFilters.slice(1).map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}</select><select value={templateFilter} onChange={(e) => setTemplateFilter(e.target.value)} className='premium-input h-9 text-xs'><option value='all'>Template</option>{templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select><select value={periodFilter} onChange={(e) => setPeriodFilter(e.target.value)} className='premium-input h-9 text-xs'><option value='all'>Período</option><option value='7'>Últimos 7 dias</option><option value='30'>Últimos 30 dias</option></select><select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} className='premium-input h-9 text-xs'><option value='all'>Tag</option></select><button className='secondary-button inline-flex h-9 items-center gap-1 px-3 text-xs font-semibold'><Filter size={13}/>Mais filtros</button></div></div>
      <div className='mt-3 flex flex-wrap gap-2'>{statusFilters.map((filter) => <button key={filter.value} onClick={() => setStatusFilter(filter.value)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${statusFilter === filter.value ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-emerald-200 hover:text-emerald-700'}`}>{filter.label}</button>)}</div>
    </div>

    {loading ? <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>{Array.from({ length: 4 }).map((_, i) => <div key={i} className='h-40 animate-pulse rounded-[18px] border border-slate-200 bg-white/80'/>)}</div> : null}

    {!loading && filteredCampaigns.length === 0 ? (<CampaignCard><div className='flex min-h-[220px] flex-col items-center justify-center rounded-[18px] border border-dashed border-slate-300 bg-white p-6 text-center'><div className='mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50'><Megaphone size={28} className='text-emerald-600'/></div><p className='text-lg font-semibold text-slate-900'>Nenhuma campanha criada</p><p className='mt-1 max-w-md text-sm font-normal text-slate-500'>Crie sua primeira campanha utilizando templates aprovados pela Meta.</p><button onClick={() => setShowCreate(true)} className='primary-button mt-5 inline-flex h-9 items-center gap-2 px-4 text-xs font-semibold'><Plus size={14}/>Criar campanha</button></div></CampaignCard>) : null}

    {!loading && filteredCampaigns.length > 0 ? <div className='overflow-hidden rounded-[18px] border border-slate-200 bg-white shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'><div className='overflow-x-auto'><table className='min-w-[1120px] w-full text-left text-sm'><thead className='bg-slate-50 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400'><tr><th className='px-5 py-3'>Campanha</th><th className='px-5 py-3'>Status</th><th className='px-5 py-3'>Template</th><th className='px-5 py-3'>Audiência</th><th className='px-5 py-3'>Enviadas</th><th className='px-5 py-3'>Entrega</th><th className='px-5 py-3'>Leitura</th><th className='px-5 py-3'>Conversões</th><th className='px-5 py-3'>Criada em</th><th className='px-5 py-3'>Ações</th></tr></thead><tbody className='divide-y divide-slate-100'>{filteredCampaigns.map((c) => { const total = c.total_recipients || 0; const delivery = (c.total_sent || 0) > 0 ? Math.round(((c.total_delivered || 0) / (c.total_sent || 1)) * 100) : 0; const reading = (c.total_delivered || 0) > 0 ? Math.round(((c.total_read || 0) / (c.total_delivered || 1)) * 100) : 0; return <tr key={c.id} className='align-top transition hover:bg-slate-50/70'><td className='px-5 py-3'><p className='font-semibold text-slate-950'>{c.name}</p><p className='mt-1 text-xs text-slate-500'>ID: {c.id}</p></td><td className='px-5 py-3'><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(c.status)}`}>{statusLabel(c.status)}</span></td><td className='px-5 py-3 text-slate-700'>{getTemplateName(c.template_id)}</td><td className='px-5 py-3 font-semibold text-slate-800'>{formatNum(total)}</td><td className='px-5 py-3 font-semibold text-slate-800'>{formatNum(c.total_sent || 0)}</td><td className='px-5 py-3 font-semibold text-slate-800'>{delivery}%</td><td className='px-5 py-3 font-semibold text-slate-800'>{reading}%</td><td className='px-5 py-3 text-slate-500'>—</td><td className='px-5 py-3 text-slate-600'>{c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : '—'}</td><td className='px-5 py-3'><div className='flex flex-wrap items-center gap-2'><button onClick={() => setShowReports(true)} className='secondary-button inline-flex items-center gap-1'><BarChart3 size={13}/>Relatório</button>{c.status === 'draft' && <button onClick={() => void onStartCampaign(c.id)} className='primary-button'>Iniciar</button>}{c.status === 'running' && <button onClick={() => void onPauseCampaign(c.id)} className='secondary-button inline-flex items-center gap-1'><PauseCircle size={13}/>Pausar</button>}</div></td></tr>; })}</tbody></table></div></div> : null}


    {showTemplates && <CampaignCreateModal><div className='max-h-[82vh] space-y-4 overflow-auto p-1'>
      <div className='flex items-start justify-between gap-3'>
        <div><h4 className='text-lg font-semibold text-slate-950'>Templates Meta</h4><p className='text-xs text-slate-500'>Centro de templates aprovados e sincronizados pela integração Meta.</p></div>
        <button onClick={() => setShowTemplates(false)} className='secondary-button'>Fechar</button>
      </div>
      <div className='rounded-[18px] border border-slate-200 bg-white p-3 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'>
        <div className='grid gap-2 lg:grid-cols-[minmax(260px,1fr)_repeat(4,minmax(130px,160px))]'>
          <label className='flex h-10 items-center gap-2 rounded-full border border-slate-200 px-3 text-sm text-slate-500 focus-within:border-emerald-300'><Search size={15}/><input value={templateSearchTerm} onChange={(e) => setTemplateSearchTerm(e.target.value)} placeholder='Buscar template...' className='w-full bg-transparent outline-none' /></label>
          <select value={templateCategoryFilter} onChange={(e) => setTemplateCategoryFilter(e.target.value)} className='premium-input h-10'><option value='all'>Categoria</option><option value='marketing'>Marketing</option><option value='utility'>Utility</option><option value='authentication'>Authentication</option>{templateCategories.filter((c) => !['all','marketing','utility','authentication'].includes(c)).map((c) => <option key={c} value={c}>{c}</option>)}</select>
          <select value={templateLanguageFilter} onChange={(e) => setTemplateLanguageFilter(e.target.value)} className='premium-input h-10'><option value='all'>Idioma</option>{['pt_BR','en_US','es_ES'].map((l) => <option key={l} value={l}>{l}</option>)}{templateLanguages.filter((l) => !['all','pt_BR','en_US','es_ES'].includes(l)).map((l) => <option key={l} value={l}>{l}</option>)}</select>
          <select value={templateStatusFilter} onChange={(e) => setTemplateStatusFilter(e.target.value)} className='premium-input h-10'><option value='all'>Status</option>{['approved','pending','rejected'].map((st) => <option key={st} value={st}>{statusLabel(st)}</option>)}{templateStatuses.filter((st) => !['all','approved','pending','rejected'].includes(st)).map((st) => <option key={st} value={st}>{statusLabel(st)}</option>)}</select>
          <select value={templateQualityFilter} onChange={(e) => setTemplateQualityFilter(e.target.value)} className='premium-input h-10'><option value='all'>Qualidade</option><option value='high'>Alta</option><option value='medium'>Média</option><option value='low'>Baixa</option></select>
        </div>
        <div className='mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500'><span>{filteredTemplates.length} de {templates.length} templates {lastTemplateSyncAt ? `• última sincronização ${new Date(lastTemplateSyncAt).toLocaleString('pt-BR')}` : ''}</span><button onClick={() => void onSyncTemplates()} disabled={syncingTemplates} className='secondary-button inline-flex items-center gap-2'>{syncingTemplates ? <Loader2 size={14} className='animate-spin'/> : <RefreshCcw size={14}/>}Sincronizar com a Meta</button></div>
      </div>
      {filteredTemplates.length === 0 ? <div className='flex min-h-[260px] flex-col items-center justify-center rounded-[22px] border border-dashed border-slate-300 bg-white p-8 text-center'><div className='mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-50'><FileText className='text-emerald-600' size={30}/></div><p className='text-lg font-semibold text-slate-950'>Nenhum template encontrado.</p><p className='mt-1 max-w-md text-sm text-slate-500'>Crie ou aprove templates no Meta Business Manager e sincronize novamente.</p><button onClick={() => void onSyncTemplates()} disabled={syncingTemplates} className='primary-button mt-5 inline-flex items-center gap-2'>{syncingTemplates ? <Loader2 size={14} className='animate-spin'/> : <RefreshCcw size={14}/>}Sincronizar com a Meta</button></div> : <div className='overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)]'><div className='overflow-x-auto'><table className='w-full min-w-[1040px] text-left text-sm'><thead className='bg-slate-50 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400'><tr><th className='px-5 py-3'>Nome</th><th className='px-5 py-3'>Categoria</th><th className='px-5 py-3'>Idioma</th><th className='px-5 py-3'>Status</th><th className='px-5 py-3'>Qualidade</th><th className='px-5 py-3'>Última sincronização</th><th className='px-5 py-3'>Ações</th></tr></thead><tbody className='divide-y divide-slate-100'>{filteredTemplates.map((template) => { const approved = normalizeTemplateStatus(template.status) === APPROVED_STATUS; return <tr key={template.id} className='align-middle transition hover:bg-slate-50/70'><td className='px-5 py-4'><p className='font-semibold text-slate-950'>{template.name}</p><p className='mt-1 line-clamp-1 max-w-md text-xs text-slate-500'>{getTemplateText(template) || '—'}</p></td><td className='px-5 py-4 text-slate-700'>{template.category || '—'}</td><td className='px-5 py-4 text-slate-700'>{template.language || '—'}</td><td className='px-5 py-4'><TemplateStatusBadge status={template.status}/></td><td className='px-5 py-4'><TemplateQualityBadge value={template.quality_rating || template.quality_score}/></td><td className='px-5 py-4 text-slate-600'>{template.updated_at ? new Date(template.updated_at).toLocaleString('pt-BR') : lastTemplateSyncAt ? new Date(lastTemplateSyncAt).toLocaleString('pt-BR') : '—'}</td><td className='px-5 py-4'><div className='flex flex-wrap gap-2'><button onClick={() => setPreviewTemplate(template)} className='secondary-button inline-flex items-center gap-1'><Eye size={13}/>Visualizar</button><button disabled={!approved} onClick={() => { setShowTemplates(false); setShowCreate(true); setTemplateId(template.id); if (template.provider_id) setProviderId(template.provider_id); }} className='primary-button disabled:opacity-50'>Selecionar para campanha</button><button type='button' className='secondary-button inline-flex items-center gap-1' disabled><Copy size={13}/>Duplicar localmente</button><button onClick={() => void onSyncTemplates()} disabled={syncingTemplates} className='secondary-button inline-flex items-center gap-1'><RefreshCcw size={13}/>Sincronizar</button></div></td></tr>; })}</tbody></table></div></div>}
    </div></CampaignCreateModal>}


    {showReports && <CampaignCreateModal><div className='max-h-[80vh] space-y-4 overflow-auto p-1'>
      <div className='flex items-center justify-between gap-3'>
        <div>
          <h4 className='text-lg font-semibold text-slate-950'>Relatórios</h4>
          <p className='text-xs font-medium text-slate-400'>Resumo Geral</p>
        </div>
        <button onClick={() => setShowReports(false)} className='secondary-button'>Fechar</button>
      </div>
      <div className='grid grid-cols-2 gap-2 md:grid-cols-5'>
        {[['Campanhas', formatNum(campaigns.length)], ['Mensagens', formatNum(metrics.sent)], ['Entregas', metrics.sent > 0 ? `${deliveryRate}%` : '—'], ['Leitura', metrics.delivered > 0 ? `${readRate}%` : '—'], ['Respostas', '—']].map(([label, value]) => <div key={label} className='rounded-2xl border border-slate-200 bg-white p-3 shadow-[0_14px_34px_-32px_rgba(15,23,42,0.35)]'><p className='text-[11px] font-medium text-slate-500'>{label}</p><p className='mt-1 text-xl font-semibold text-slate-950'>{value}</p></div>)}
      </div>
      {campaigns.length === 0 ? <div className='rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center'><BarChart3 className='mx-auto mb-3 text-slate-300' size={28}/><p className='font-semibold text-slate-950'>Sem dados</p><div className='mt-4 flex justify-center gap-2'><button disabled className='secondary-button inline-flex items-center gap-2'><Loader2 size={14}/>Exportar CSV</button><button disabled className='secondary-button'>Exportar PDF</button></div></div> : <div className='flex flex-wrap gap-2'><button className='secondary-button'>Exportar CSV</button><button className='secondary-button'>Exportar PDF</button></div>}
    </div></CampaignCreateModal>}

    {previewTemplate ? <TemplatePreview template={previewTemplate} onClose={() => setPreviewTemplate(null)} /> : null}

    {showCreate && <CampaignCreateModal><div className='space-y-3'>
      <h4 className='font-semibold'>Nova campanha</h4>
      <div className='flex flex-wrap gap-1'>{[1,2,3,4,5,6].map((step) => <button key={step} type='button' onClick={() => setWizardStep(step)} className={`rounded-full border px-2 py-1 text-xs ${wizardStep === step ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-200 bg-white text-slate-600'}`}>Etapa {step}</button>)}</div>
      <div className='rounded-xl border border-slate-200 bg-slate-50 p-3'>
        <p className='mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500'>Etapa 1 — Objetivo</p>
        <select value={campaignObjective} onChange={(e) => setCampaignObjective(e.target.value)} className='premium-input w-full'>{['Promoção','Cobrança','Pós-venda','Lembrete','Pesquisa','Recuperação','Personalizada'].map((objective) => <option key={objective} value={objective}>{objective}</option>)}</select>
      </div>
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
      <div className='flex flex-wrap items-center gap-2'>
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

      <div className='rounded-xl border border-slate-200 bg-white p-3'>
        <p className='mb-2 text-sm font-semibold'>Etapa 6 — Envio</p>
        <div className='flex flex-wrap gap-2 text-xs'>{(['draft','now','schedule'] as const).map((mode) => <button key={mode} type='button' onClick={() => setSendMode(mode)} className={`rounded border px-3 py-1.5 ${sendMode === mode ? 'bg-slate-900 text-white' : 'bg-white text-slate-700'}`}>{mode === 'draft' ? 'Salvar rascunho' : mode === 'now' ? 'Enviar agora' : 'Agendar'}</button>)}</div>
        {sendMode === 'schedule' && <input type='datetime-local' value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className='premium-input mt-2 w-full' />}
        <p className='mt-2 text-xs text-slate-500'>Revisão: {name || 'Sem nome'} • {selectedTemplate?.name || 'Sem template'} • audiência estimada {recipientMode === 'csv' ? parseLeads().length : selectedContactIds.length} • variáveis {templateVariables.join(', ') || 'nenhuma'}.</p>
      </div>

      {(hasCreateErrors || hasVariableErrors || hasRecipientVariableErrors) && <p className='text-xs text-amber-600'>Preencha nome, provider/template e todos os mapeamentos obrigatórios para continuar. Edite o contato em Contatos ou use valor fixo.</p>}
      <div className='flex justify-end gap-2'>
        <button onClick={() => setShowCreate(false)} className='secondary-button'>Cancelar</button>
        <button onClick={() => void onCreate()} disabled={hasCreateErrors || hasVariableErrors || hasRecipientVariableErrors || creatingCampaign} className='primary-button inline-flex items-center gap-2'>
          {creatingCampaign ? <Loader2 size={14} className='animate-spin'/> : null}{sendMode === 'draft' ? 'Salvar rascunho' : sendMode === 'schedule' ? 'Agendar' : 'Enviar agora'}
        </button>
      </div>
    </div></CampaignCreateModal>}
  </div>;
}
