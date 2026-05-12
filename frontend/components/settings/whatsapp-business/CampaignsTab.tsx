'use client';

import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { Loader2, Megaphone, Plus, RefreshCcw, Send } from 'lucide-react';
import CampaignCard from './campaigns/CampaignCard';
import CampaignCreateModal from './campaigns/CampaignCreateModal';
import CampaignStats from './campaigns/CampaignStats';
import CampaignStatusBadge from './campaigns/CampaignStatusBadge';
import {
  createWhatsAppCampaign,
  importWhatsAppCampaignRecipients,
  importWhatsAppCampaignRecipientsFromContacts,
  getContacts,
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

const APPROVED_STATUS = 'approved';
const MANUAL_VALUE_FIELD = 'manual_value';
const VARIABLE_FIELD_OPTIONS: VariableFieldOption[] = [
  { value: 'first_name', label: 'Primeiro nome', csvColumn: 'primeiro_nome' },
  { value: 'full_name', label: 'Nome completo', csvColumn: 'nome_completo' },
  { value: 'phone', label: 'Telefone', csvColumn: 'telefone' },
  { value: 'email', label: 'E-mail', csvColumn: 'email' },
  { value: 'company', label: 'Empresa', csvColumn: 'empresa' },
  { value: 'order_number', label: 'Número do pedido', csvColumn: 'numero_pedido' },
  { value: 'product', label: 'Produto', csvColumn: 'produto' },
  { value: 'order_value', label: 'Valor do pedido', csvColumn: 'valor_pedido' },
  { value: 'order_status', label: 'Status do pedido', csvColumn: 'status_pedido' },
  { value: 'tracking_link', label: 'Link de rastreio', csvColumn: 'link_rastreio' },
  { value: 'custom_field', label: 'Campo personalizado', csvColumn: 'campo_personalizado' },
  { value: MANUAL_VALUE_FIELD, label: 'Valor manual', csvColumn: 'valor_manual' }
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

export default function CampaignsTab() {
  const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [savedContacts, setSavedContacts] = useState<CRMContact[]>([]);
  const [selectedContactIds, setSelectedContactIds] = useState<string[]>([]);
  const [recipientMode, setRecipientMode] = useState<'csv' | 'saved'>('csv');
  const [contactSearch, setContactSearch] = useState('');
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

  const refresh = async () => {
    setLoading(true);
    try {
      setCampaigns(await listWhatsAppCampaigns());
      setSavedContacts(await getContacts());
    } finally {
      setLoading(false);
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
      acc[key] = field === MANUAL_VALUE_FIELD ? manualVariableValues[key] || '' : testVariableValues[key] || '';
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
    if (!name || !providerId || !templateId) return;
    const created = await createWhatsAppCampaign({ name, provider_id: providerId, template_id: templateId });
    const leads = parseLeads();
    if (recipientMode === 'csv' && leads.length) {
      await importWhatsAppCampaignRecipients(
        created.id,
        leads.map((item) => ({ phone: item.phone, variables_json: item.fields }))
      );
    }
    if (recipientMode === 'saved' && selectedContactIds.length) {
      await importWhatsAppCampaignRecipientsFromContacts(created.id, { contact_ids: selectedContactIds, variables_json: {"1": "first_name", "2": variableMapping["2"] || "custom_fields_json.order_id"}, manual_variable_2: manualVariableValues["2"] || "" });
    }
    setName('');
    setProviderId('');
    setTemplateId('');
    setLeadsText('');
    setShowCreate(false);
    await refresh();
  };
  const onStartCampaign = async (campaignId: string) => {
    await startWhatsAppCampaign(campaignId);
    await refresh();
  };
  const onPauseCampaign = async (campaignId: string) => {
    await pauseWhatsAppCampaign(campaignId);
    await refresh();
  };

  const hasCreateErrors = !name || !providerId || !templateId;
  const hasVariableErrors = templateVariables.some((key) => !variableMapping[key] || (variableMapping[key] === MANUAL_VALUE_FIELD && !manualVariableValues[key]));
  const csvHeaders = ['telefone', ...templateVariables.map((key) => VARIABLE_FIELD_OPTIONS.find((item) => item.value === variableMapping[key])?.csvColumn || `variavel_${key}`)];

  return <div className='space-y-4 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5'>
    <div className='flex items-center justify-between'>
      <h3 className='inline-flex items-center gap-2 text-lg font-semibold text-slate-900'><Megaphone size={18}/>Campanhas</h3>
      <div className='flex gap-2'>
        <button onClick={() => void refresh()} className='secondary-button inline-flex items-center gap-2'><RefreshCcw size={14}/>Atualizar</button>
        <button onClick={() => setShowCreate(true)} className='primary-button inline-flex items-center gap-2'><Plus size={14}/>Nova campanha</button>
      </div>
    </div>

    <CampaignStats><div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>{[['campanhas ativas', metrics.active], ['enviados', metrics.sent], ['entregues', metrics.delivered], ['lidos', metrics.read], ['falhas', metrics.failed]].map(([k,v]) => <div key={String(k)} className='rounded-xl border border-slate-200 p-3'><p className='text-xs text-slate-500'>{k}</p><p className='text-xl font-semibold'>{v}</p></div>)}</div></CampaignStats>

    {campaigns.length === 0 ? (<CampaignCard><div className='rounded-xl border border-dashed border-slate-300 bg-slate-50/80 p-8 text-center'><p className='text-sm font-medium text-slate-600'>Nenhuma campanha criada ainda.</p><p className='mt-1 text-xs text-slate-500'>Clique em “Nova campanha” para começar.</p></div></CampaignCard>) : (<div className='space-y-3'>{campaigns.map(c => {
      const total = c.total_recipients || 0;
      const done = (c.total_sent || 0) + (c.total_failed || 0);
      const progress = total > 0 ? Math.round((done / total) * 100) : 0;
      return <CampaignCard key={c.id}><div className='space-y-3'>
        <div className='flex items-center justify-between'><div><p className='font-semibold text-slate-900'>{c.name}</p><p className='text-xs text-slate-500'>ID: {c.id}</p></div><CampaignStatusBadge>{c.status}</CampaignStatusBadge></div>
        <div className='grid grid-cols-2 gap-2 text-xs text-slate-600 sm:grid-cols-6'>
          <p>Total: <strong>{total}</strong></p><p>Enviados: <strong>{c.total_sent || 0}</strong></p><p>Falhas: <strong>{c.total_failed || 0}</strong></p><p>Entregues: <strong>{c.total_delivered || 0}</strong></p><p>Lidos: <strong>{c.total_read || 0}</strong></p><p>Progresso: <strong>{progress}%</strong></p>
        </div>
        <div className='h-2 rounded-full bg-slate-100'><div className='h-2 rounded-full bg-emerald-500' style={{ width: `${progress}%` }}/></div>
        <div className='flex gap-2'>
          {c.status === 'draft' && <button onClick={() => void onStartCampaign(c.id)} className='primary-button'>Iniciar campanha</button>}
          {c.status === 'running' && <button onClick={() => void onPauseCampaign(c.id)} className='secondary-button'>Pausar</button>}
          <button onClick={() => void refresh()} className='secondary-button'>Atualizar</button>
        </div>
      </div></CampaignCard>;
    })}</div>)}

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
              {variableMapping[key] === MANUAL_VALUE_FIELD && <input value={manualVariableValues[key] || ''} onChange={(e) => setManualVariableValues((prev) => ({ ...prev, [key]: e.target.value }))} placeholder='Digite um valor manual' className='premium-input mt-2 w-full' />}
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
          <button type='button' onClick={() => setRecipientMode('saved')} className={`rounded border px-2 py-1 ${recipientMode === 'saved' ? 'bg-slate-900 text-white' : 'bg-white'}`}>Selecionar contatos salvos</button>
        </div>
        {recipientMode === 'csv' && <><p className='mb-2 text-xs text-slate-500'>CSV esperado: {csvHeaders.join(',')}</p>
        <textarea value={leadsText} onChange={(e) => setLeadsText(e.target.value)} rows={5} className='premium-input w-full' placeholder={`${csvHeaders.join(',')}
5516999999999,Gabriel,#4821`} />
        <label className='mt-2 block text-xs text-slate-500'>Upload CSV
          <input type='file' accept='.csv,text/csv' onChange={(e) => void onCsvUpload(e)} className='mt-1 block text-xs' />
        </label></>}

        {recipientMode === 'saved' && <div className='space-y-2'>
          <input value={contactSearch} onChange={(e) => setContactSearch(e.target.value)} placeholder='Buscar por nome/telefone' className='premium-input w-full' />
          <div className='max-h-40 space-y-1 overflow-auto rounded border p-2'>
            {savedContacts.filter((c) => !contactSearch || `${c.name || ''} ${c.phone}`.toLowerCase().includes(contactSearch.toLowerCase())).map((c) => (
              <label key={c.id} className='flex items-center gap-2 text-xs'>
                <input type='checkbox' checked={selectedContactIds.includes(c.id)} onChange={(e) => setSelectedContactIds((prev) => e.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id))} />
                <span>{c.name || c.phone} • {c.phone} • {c.source || 'whatsapp'}</span>
              </label>
            ))}
          </div>
        </div>}
      </div>

      {(hasCreateErrors || hasVariableErrors) && <p className='text-xs text-amber-600'>Preencha nome, provider/template e todos os mapeamentos obrigatórios para continuar.</p>}
      <div className='flex justify-end gap-2'>
        <button onClick={() => setShowCreate(false)} className='secondary-button'>Cancelar</button>
        <button onClick={() => void onCreate()} disabled={hasCreateErrors || hasVariableErrors || loading} className='primary-button inline-flex items-center gap-2'>
          {loading ? <Loader2 size={14} className='animate-spin'/> : null}Criar
        </button>
      </div>
    </div></CampaignCreateModal>}
  </div>;
}
