'use client';
import { memo } from 'react';

export default memo(function ContactMetrics({ profile }: { profile: any }) {
  const metrics = [
    ['Mensagens', profile?.messages_count ?? 0],
    ['Campanhas', profile?.campaigns_received ?? 0],
    ['Flows', profile?.flows_executed ?? 0],
    ['Última campanha', profile?.last_campaign_at ? new Date(profile.last_campaign_at).toLocaleDateString('pt-BR') : '-'],
    ['Taxa resposta', `${profile?.response_rate ?? 0}%`]
  ];
  return <div className='grid grid-cols-1 gap-2'>
    {metrics.map(([label, value]) => <div key={String(label)} className='rounded-xl border border-slate-200 bg-white p-3 shadow-sm'><p className='text-xs text-slate-500'>{label}</p><p className='text-lg font-semibold text-slate-800'>{value}</p></div>)}
  </div>;
});
