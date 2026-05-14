'use client';

export default function TimelineEventCard({ event }: { event: any }) {
  const type = event.type || 'note_added';
  const icon = type.includes('message') ? '💬' : type.includes('campaign') ? '📣' : type.includes('flow') ? '🧠' : type.includes('tag') ? '🏷️' : '📝';
  const inbound = type === 'message_received';
  const outbound = type === 'message_sent';

  if (inbound || outbound) {
    return <div className={`flex ${outbound ? 'justify-end' : 'justify-start'}`}><div className={`max-w-[78%] rounded-2xl px-4 py-2 shadow-sm ${outbound ? 'bg-emerald-500 text-white' : 'bg-slate-100 text-slate-800'}`}><p className='text-sm'>{event.description || event.title || 'Mensagem'}</p><p className={`mt-1 text-[11px] ${outbound ? 'text-emerald-100' : 'text-slate-500'}`}>{new Date(event.created_at || Date.now()).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</p></div></div>;
  }

  return <div className='rounded-xl border border-slate-200 bg-white p-3 shadow-sm'>
    <p className='text-sm font-medium text-slate-800'>{icon} {event.title || type}</p>
    <p className='text-sm text-slate-600'>{event.description || '-'}</p>
  </div>;
}
