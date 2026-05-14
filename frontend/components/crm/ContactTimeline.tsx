'use client';

import { memo } from 'react';
import TimelineEventCard from './TimelineEventCard';

function ContactTimeline({ events, loading }: { events: any[]; loading?: boolean }) {
  if (loading) return <div className='space-y-2'>{Array.from({ length: 5 }).map((_, i) => <div key={i} className='h-16 animate-pulse rounded-xl bg-slate-100'/>)}</div>;
  if (!events.length) return <div className='rounded-xl border border-dashed border-slate-300 bg-gradient-to-b from-white to-slate-50 p-8 text-center text-slate-500'>Timeline vazia por enquanto. Assim que houver mensagens, campanhas e flows, tudo aparecerá aqui em tempo real.</div>;
  return <div className='max-h-[72vh] space-y-3 overflow-y-auto pr-1'>{events.map((event) => <TimelineEventCard key={event.id || `${event.type}-${event.created_at}`} event={event} />)}</div>;
}

export default memo(ContactTimeline);
