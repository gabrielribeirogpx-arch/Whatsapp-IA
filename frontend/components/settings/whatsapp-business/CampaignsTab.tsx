'use client';
import { useEffect, useMemo, useState } from 'react';
import { Megaphone, Plus, RefreshCcw } from 'lucide-react';
import CampaignCard from './campaigns/CampaignCard';
import CampaignCreateModal from './campaigns/CampaignCreateModal';
import CampaignStats from './campaigns/CampaignStats';
import CampaignStatusBadge from './campaigns/CampaignStatusBadge';
import { createWhatsAppCampaign, listWhatsAppCampaigns } from '@/lib/api';
import { WhatsAppCampaign } from '@/lib/types';

export default function CampaignsTab() {
  const [campaigns, setCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState('');
  const [templateId, setTemplateId] = useState('');

  const refresh = async () => {
    setLoading(true);
    try {
      setCampaigns(await listWhatsAppCampaigns());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  const metrics = useMemo(() => {
    const active = campaigns.filter(c => ['running', 'scheduled'].includes(c.status)).length;
    return {
      active,
      sent: campaigns.reduce((acc, c) => acc + (c.total_sent || 0), 0),
      delivered: campaigns.reduce((acc, c) => acc + (c.total_delivered || 0), 0),
      read: campaigns.reduce((acc, c) => acc + (c.total_read || 0), 0),
      failed: campaigns.reduce((acc, c) => acc + (c.total_failed || 0), 0)
    };
  }, [campaigns]);

  const onCreate = async () => {
    await createWhatsAppCampaign({ name, provider_id: providerId, template_id: templateId });
    setName(''); setProviderId(''); setTemplateId(''); setShowCreate(false);
    await refresh();
  };

  return <div className='space-y-4 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5'>
    <div className='flex items-center justify-between'>
      <h3 className='inline-flex items-center gap-2 text-lg font-semibold text-slate-900'><Megaphone size={18}/>Campanhas</h3>
      <div className='flex gap-2'>
        <button onClick={() => void refresh()} className='secondary-button inline-flex items-center gap-2'><RefreshCcw size={14}/>Atualizar</button>
        <button onClick={() => setShowCreate(true)} className='primary-button inline-flex items-center gap-2'><Plus size={14}/>Nova campanha</button>
      </div>
    </div>

    <CampaignStats>
      <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        {[
          ['campanhas ativas', metrics.active], ['enviados', metrics.sent], ['entregues', metrics.delivered], ['lidos', metrics.read], ['falhas', metrics.failed]
        ].map(([k,v]) => <div key={String(k)} className='rounded-xl border border-slate-200 p-3'><p className='text-xs text-slate-500'>{k}</p><p className='text-xl font-semibold'>{v}</p></div>)}
      </div>
    </CampaignStats>

    {campaigns.length === 0 ? (
      <CampaignCard>
        <div className='rounded-xl border border-dashed border-slate-300 bg-slate-50/80 p-8 text-center'>
          <p className='text-sm font-medium text-slate-600'>Nenhuma campanha criada ainda.</p>
          <p className='mt-1 text-xs text-slate-500'>Clique em “Nova campanha” para começar.</p>
        </div>
      </CampaignCard>
    ) : (
      <div className='space-y-3'>
        {campaigns.map(c => <CampaignCard key={c.id}><div className='flex items-center justify-between'><div><p className='font-semibold text-slate-900'>{c.name}</p><p className='text-xs text-slate-500'>ID: {c.id}</p></div><CampaignStatusBadge>{c.status}</CampaignStatusBadge></div></CampaignCard>)}
      </div>
    )}

    {showCreate && <CampaignCreateModal>
      <div className='space-y-2'>
        <h4 className='font-semibold'>Nova campanha</h4>
        <input value={name} onChange={e => setName(e.target.value)} placeholder='Nome da campanha' className='premium-input w-full' />
        <input value={providerId} onChange={e => setProviderId(e.target.value)} placeholder='Provider ID' className='premium-input w-full' />
        <input value={templateId} onChange={e => setTemplateId(e.target.value)} placeholder='Template ID' className='premium-input w-full' />
        <div className='flex justify-end gap-2'>
          <button onClick={() => setShowCreate(false)} className='secondary-button'>Cancelar</button>
          <button onClick={() => void onCreate()} disabled={!name || !providerId || !templateId || loading} className='primary-button'>Criar</button>
        </div>
      </div>
    </CampaignCreateModal>}
  </div>;
}
