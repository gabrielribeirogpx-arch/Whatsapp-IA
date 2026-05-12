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
  listTemplates,
  listWhatsAppCampaigns,
  listWhatsAppProviders,
  sendMessage
} from '@/lib/api';
import { WhatsAppCampaign, WhatsAppProvider, WhatsAppTemplate } from '@/lib/types';

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

function parseTemplateVariables(rawText: string): string[] {
  const matches = rawText.match(/\{\{\s*(\d+)\s*\}\}/g) || [];
  const unique = Array.from(new Set(matches.map((v) => v.replace(/[^\d]/g, ''))));
  return unique.sort((a, b) => Number(a) - Number(b));
}

export default function CampaignsTab() {
  const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
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

  const refresh = async () => {
    setLoading(true);
    try {
      setCampaigns(await listWhatsAppCampaigns());
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
  const templateBody = selectedTemplate?.body_preview || selectedTemplate?.body_text || '';
  const templateVariables = useMemo(() => parseTemplateVariables(templateBody), [templateBody]);

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
    setTestVariableValues((prev) => templateVariables.reduce((acc, key) => ({ ...acc, [key]: prev[key] || '' }), {}));
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
    return templateBody.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, key: string) => `**${variableValues[key] || `Variável ${key}`}**`);
  };

  const onQuickTest = async () => {
    if (!testPhone || !selectedTemplate) return;
    const payloadVariables = templateVariables.reduce<Record<string, string>>((acc, key) => {
      acc[key] = variableValues[key] || '';
      return acc;
    }, {});
    console.log('quick_test_payload', { phone: testPhone, variables: payloadVariables, variable_mapping: variableMapping });
    await sendMessage(testPhone, renderPreview().replace(/\*\*/g, ''));
  };

  const onCreate = async () => {
    if (!name || !providerId || !templateId) return;
    const created = await createWhatsAppCampaign({ name, provider_id: providerId, template_id: templateId });
    const leads = parseLeads();
    if (leads.length) {
      await importWhatsAppCampaignRecipients(
        created.id,
        leads.map((item) => ({ phone: item.phone, variables_json: item.fields }))
      );
    }
    setName('');
    setProviderId('');
    setTemplateId('');
    setLeadsText('');
    setShowCreate(false);
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

    {campaigns.length === 0 ? (<CampaignCard><div className='rounded-xl border border-dashed border-slate-300 bg-slate-50/80 p-8 text-center'><p className='text-sm font-medium text-slate-600'>Nenhuma campanha criada ainda.</p><p className='mt-1 text-xs text-slate-500'>Clique em “Nova campanha” para começar.</p></div></CampaignCard>) : (<div className='space-y-3'>{campaigns.map(c => <CampaignCard key={c.id}><div className='flex items-center justify-between'><div><p className='font-semibold text-slate-900'>{c.name}</p><p className='text-xs text-slate-500'>ID: {c.id}</p></div><CampaignStatusBadge>{c.status}</CampaignStatusBadge></div></CampaignCard>)}</div>)}

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
          {templateVariables.map((key) => (
            <div key={`test-${key}`} className='grid grid-cols-1 gap-2 md:grid-cols-2'>
              <input value={VARIABLE_FIELD_OPTIONS.find((item) => item.value === variableMapping[key])?.label || ''} readOnly className='premium-input w-full bg-slate-100' placeholder={`Campo da variável ${key}`} />
              <input value={testVariableValues[key] || ''} onChange={(e) => setTestVariableValues((prev) => ({ ...prev, [key]: e.target.value }))} placeholder={`Valor de teste da variável ${key}`} className='premium-input w-full' />
            </div>
          ))}
        </div>
        <button onClick={() => void onQuickTest()} disabled={!testPhone || !selectedTemplate || hasVariableErrors} className='secondary-button mt-3 inline-flex items-center gap-2'><Send size={14}/>Enviar teste</button>
      </div>

      <div className='rounded-xl border border-slate-200 p-3'>
        <p className='mb-2 text-sm font-semibold'>Importação de leads</p>
        <p className='mb-2 text-xs text-slate-500'>CSV esperado: {csvHeaders.join(',')}</p>
        <textarea value={leadsText} onChange={(e) => setLeadsText(e.target.value)} rows={5} className='premium-input w-full' placeholder={`${csvHeaders.join(',')}
5516999999999,Gabriel,#4821`} />
        <label className='mt-2 block text-xs text-slate-500'>Upload CSV
          <input type='file' accept='.csv,text/csv' onChange={(e) => void onCsvUpload(e)} className='mt-1 block text-xs' />
        </label>
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
