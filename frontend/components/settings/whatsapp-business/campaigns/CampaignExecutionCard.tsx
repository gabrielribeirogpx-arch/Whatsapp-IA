import { WhatsAppCampaign } from '@/lib/types';
import CampaignProgressBar, { campaignProgress } from './CampaignProgressBar';

function elapsed(startedAt?: string | null) {
  if (!startedAt) return '—';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)}h ${minutes % 60}min`;
}

export default function CampaignExecutionCard({ campaign }: { campaign: WhatsAppCampaign }) {
  const progress = campaignProgress(campaign);
  const sent = campaign.total_sent || 0;
  const failed = campaign.total_failed || 0;
  const durationSeconds = campaign.started_at ? Math.max(1, (Date.now() - new Date(campaign.started_at).getTime()) / 1000) : null;
  const speed = durationSeconds && sent + failed > 0 ? Math.round(((sent + failed) / durationSeconds) * 60) : null;
  const eta = speed && progress.pending > 0 ? Math.ceil(progress.pending / speed) : null;
  return <section className='rounded-[18px] border border-slate-200 bg-white p-4'>
    <div className='mb-3 flex items-start justify-between gap-3'><div><p className='font-semibold text-slate-950'>{campaign.name}</p><p className='text-xs text-slate-500'>Início: {campaign.started_at ? new Date(campaign.started_at).toLocaleString('pt-BR') : '—'} · Duração: {elapsed(campaign.started_at)}</p></div><p className='text-xl font-bold text-emerald-700'>{progress.percent}%</p></div>
    <CampaignProgressBar campaign={campaign} />
    <div className='mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-6'>{[
      ['Enviadas', campaign.total_sent], ['Entregues', campaign.total_delivered], ['Lidas', campaign.total_read], ['Falhas', campaign.total_failed], ['Pendentes', progress.pending], ['Velocidade', speed ? `${speed}/min` : '—']
    ].map(([label, value]) => <div key={label} className='rounded-xl bg-slate-50 p-2'><p className='text-slate-500'>{label}</p><p className='font-bold text-slate-900'>{typeof value === 'number' ? value.toLocaleString('pt-BR') : value}</p></div>)}</div>
    <p className='mt-3 text-xs text-slate-500'>ETA: {eta ? `${eta} min` : '—'}</p>
  </section>;
}
