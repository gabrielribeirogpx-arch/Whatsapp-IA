'use client';

import { memo } from 'react';
import TimelineEventCard from './TimelineEventCard';

function ContactTimeline({ events, loading }: { events: any[]; loading?: boolean }) {
  if (loading) return <div className='space-y-2'>{Array.from({ length: 4 }).map((_, i) => <div key={i} className='h-16 animate-pulse rounded-xl bg-slate-100'/>)}</div>;
  if (!events.length) return <div className='rounded-xl border border-dashed border-slate-300 p-6 text-center text-slate-500'>Nenhum evento na timeline ainda.</div>;
  return <div className='space-y-3'>{events.map((event) => <TimelineEventCard key={event.id || `${event.type}-${event.created_at}`} event={event} />)}</div>;
}

export default memo(ContactTimeline);
