import { WhatsAppCampaign } from '@/lib/types';

export function campaignProgress(campaign: WhatsAppCampaign) {
  const total = campaign.total_recipients || 0;
  const processed = (campaign.total_sent || 0) + (campaign.total_failed || 0);
  const percent = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  return { total, processed, pending: Math.max(total - processed, 0), percent };
}

export default function CampaignProgressBar({ campaign, compact = false }: { campaign: WhatsAppCampaign; compact?: boolean }) {
  const progress = campaignProgress(campaign);
  return <div className={compact ? 'min-w-[150px]' : 'space-y-2'}>
    <div className='flex items-center justify-between gap-3 text-xs font-semibold text-slate-700'>
      <span>{progress.percent}%</span>
      <span className='text-slate-500'>{progress.processed.toLocaleString('pt-BR')} / {progress.total.toLocaleString('pt-BR')}</span>
    </div>
    <div className='h-2 overflow-hidden rounded-full bg-slate-100' aria-label={`Progresso ${progress.percent}%`}>
      <div className='h-full rounded-full bg-emerald-500 transition-all duration-500' style={{ width: `${progress.percent}%` }} />
    </div>
  </div>;
}
