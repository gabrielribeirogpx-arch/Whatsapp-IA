'use client';

const iconMap: Record<string, string> = {
  message_received: '📩',
  message_sent: '📤',
  campaign_sent: '🚀',
  flow_started: '🤖',
  flow_completed: '✅',
  tag_added: '🏷️',
  note_added: '📝',
};

export default function TimelineEventCard({ event, highlighted }: { event: any; highlighted?: boolean }) {
  const type = event.type || 'note_added';
  const icon = iconMap[type] || '📝';
  const inbound = type === 'message_received';
  const outbound = type === 'message_sent';

  if (inbound || outbound) {
    return <div className={`flex ${outbound ? 'justify-end' : 'justify-start'} animate-[fadeIn_.25s_ease]`}><div className={`max-w-[78%] rounded-2xl px-4 py-2 shadow-sm ${outbound ? 'bg-emerald-500 text-white' : 'bg-slate-100 text-slate-800'}`}><p className='text-sm'>{event.description || event.title || 'Mensagem'}</p><p className={`mt-1 text-[11px] ${outbound ? 'text-emerald-100' : 'text-slate-500'}`}>{new Date(event.created_at || Date.now()).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</p></div></div>;
  }

  return <div className={`rounded-xl border bg-white p-3 shadow-sm animate-[fadeIn_.25s_ease] transition-colors ${highlighted ? 'border-emerald-300 bg-emerald-50/60' : 'border-slate-200'}`}>
    <p className='text-xs uppercase tracking-wide text-slate-400'>{type}</p>
    <p className='text-sm font-medium text-slate-800'>{icon} {event.title || type}</p>
    <p className='text-sm text-slate-600'>{event.description || '-'}</p>
    <p className='mt-1 text-[11px] text-slate-400'>{new Date(event.created_at || Date.now()).toLocaleString('pt-BR')}</p>
  </div>;
}
