import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { listWhatsAppCampaignRecipients } from '@/lib/api';
import { WhatsAppCampaign, WhatsAppCampaignRecipient, WhatsAppTemplate } from '@/lib/types';
import CampaignExecutionCard from './CampaignExecutionCard';
import CampaignStatusBadge from './CampaignStatusBadge';

function maskPhone(phone: string) { return phone.length > 6 ? `${phone.slice(0, 4)}****${phone.slice(-2)}` : phone; }
function category(error?: string | null) { const e = String(error || '').toLowerCase(); if (e.includes('variável')) return 'variável'; if (e.includes('template')) return 'template'; if (e.includes('limit')) return 'limite'; if (e.includes('policy')) return 'política'; if (e.includes('timeout') || e.includes('tempor')) return 'erro temporário'; return e ? 'erro desconhecido' : '—'; }

export default function CampaignDetailsDrawer({ campaign, template, onClose, actions }: { campaign: WhatsAppCampaign; template?: WhatsAppTemplate; onClose: () => void; actions: React.ReactNode }) {
  const [tab, setTab] = useState('overview');
  const [recipients, setRecipients] = useState<WhatsAppCampaignRecipient[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => { let active = true; setLoading(true); listWhatsAppCampaignRecipients(campaign.id).then((rows) => { if (active) setRecipients(rows); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [campaign.id]);
  const failures = useMemo(() => recipients.filter((r) => r.status.includes('failed')).reduce<Record<string, WhatsAppCampaignRecipient[]>>((acc, r) => { const key = category(r.error_message); acc[key] = [...(acc[key] || []), r]; return acc; }, {}), [recipients]);
  const tabs = [['overview','Visão geral'], ['execution','Execução'], ['recipients','Destinatários'], ['failures','Falhas'], ['template','Template'], ['activity','Atividades']];
  return <aside className='fixed inset-y-0 right-0 z-[80] flex w-full max-w-5xl flex-col border-l border-slate-200 bg-white shadow-2xl'>
    <header className='flex items-start justify-between gap-3 border-b border-slate-100 p-5'><div><div className='flex flex-wrap items-center gap-2'><h2 className='text-lg font-semibold text-slate-950'>{campaign.name}</h2><CampaignStatusBadge status={campaign.status} showDescription /></div><p className='mt-1 text-xs text-slate-500'>ID: {campaign.id}</p></div><button onClick={onClose} className='secondary-button inline-flex items-center gap-2'><X size={14}/>Fechar</button></header>
    <nav className='flex gap-2 overflow-x-auto border-b border-slate-100 px-5 py-3'>{tabs.map(([id,label]) => <button key={id} onClick={() => setTab(id)} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${tab === id ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}`}>{label}</button>)}</nav>
    <div className='flex-1 overflow-auto p-5'>
      {tab === 'overview' && <div className='grid gap-3 md:grid-cols-2'>{[['Nome', campaign.name], ['Status', campaign.status], ['Template', template?.name || campaign.template_id], ['Objetivo', String(campaign.metadata_json?.objective || '—')], ['Audiência', String(campaign.total_recipients || 0)], ['Remetente', campaign.provider_id], ['Criação', campaign.created_at ? new Date(campaign.created_at).toLocaleString('pt-BR') : '—'], ['Agendamento', campaign.scheduled_at ? new Date(campaign.scheduled_at).toLocaleString('pt-BR') : '—'], ['Início', campaign.started_at ? new Date(campaign.started_at).toLocaleString('pt-BR') : '—'], ['Término', campaign.completed_at ? new Date(campaign.completed_at).toLocaleString('pt-BR') : '—']].map(([k,v]) => <div key={k} className='rounded-2xl bg-slate-50 p-3'><p className='text-xs text-slate-500'>{k}</p><p className='font-semibold text-slate-900'>{v}</p></div>)}</div>}
      {tab === 'execution' && <div className='space-y-4'><CampaignExecutionCard campaign={campaign}/><div className='flex flex-wrap gap-2'>{actions}</div></div>}
      {tab === 'recipients' && <div className='overflow-x-auto rounded-2xl border border-slate-200'><table className='w-full min-w-[760px] text-sm'><thead className='bg-slate-50 text-xs text-slate-500'><tr><th className='p-3 text-left'>Telefone</th><th className='p-3 text-left'>Nome</th><th className='p-3 text-left'>Status</th><th className='p-3 text-left'>Horário</th><th className='p-3 text-left'>Erro</th></tr></thead><tbody>{loading ? <tr><td className='p-4' colSpan={5}>Carregando...</td></tr> : recipients.map((r) => <tr key={r.id} className='border-t border-slate-100'><td className='p-3'>{maskPhone(r.phone)}</td><td className='p-3'>{r.first_name || '—'}</td><td className='p-3'>{r.status}</td><td className='p-3'>—</td><td className='p-3'>{r.error_message || '—'}</td></tr>)}</tbody></table></div>}
      {tab === 'failures' && <div className='space-y-3'>{Object.keys(failures).length ? Object.entries(failures).map(([key, rows]) => <div key={key} className='rounded-2xl border border-rose-100 bg-rose-50 p-3'><p className='font-semibold text-rose-800'>{key}: {rows.length}</p><p className='text-xs text-rose-700'>Mensagem amigável: revise os dados dos destinatários ou o template antes de nova campanha.</p><p className='mt-1 text-xs text-rose-600'>Exemplo técnico: {rows[0]?.error_message || '—'}</p></div>) : <p className='text-sm text-slate-500'>Nenhuma falha registrada.</p>}</div>}
      {tab === 'template' && <pre className='whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 text-sm text-slate-700'>{template?.body_text || template?.body_preview || '—'}</pre>}
      {tab === 'activity' && <ol className='space-y-2 text-sm text-slate-700'>{[['criada', campaign.created_at], ['agendada', campaign.scheduled_at], ['iniciada', campaign.started_at], ['concluída', campaign.completed_at]].map(([label, date]) => date ? <li key={label} className='rounded-xl bg-slate-50 p-3'>{label}: {new Date(date).toLocaleString('pt-BR')}</li> : null)}</ol>}
    </div>
  </aside>;
}
