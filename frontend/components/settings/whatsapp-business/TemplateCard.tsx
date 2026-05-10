import { CalendarDays, MessageCircleMore } from 'lucide-react';
import { StatusBadge, toLocalDate } from './ui';

export default function TemplateCard({ t, onSubmit, loading }: { t: any; onSubmit: any; loading: boolean }) {
  return <article className='rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg'>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div>
        <p className='text-sm font-semibold text-slate-900'>{t.name}</p>
        <p className='mt-1 text-xs text-slate-500'>{t.category} · {t.language}</p>
      </div>
      <StatusBadge value={t.status} />
    </div>
    <div className='mt-3 rounded-2xl border border-emerald-100 bg-[#e9f9ee] p-3'>
      <div className='mb-2 text-[11px] font-medium text-emerald-900'>Preview WhatsApp</div>
      <div className='rounded-xl bg-white p-3 text-sm text-slate-700 shadow-sm'>
        <p className='font-medium text-slate-900'>Header</p>
        <p className='mt-1'>{t.body_text?.slice(0, 140) || 'Mensagem do template...'}</p>
        <p className='mt-2 text-xs text-slate-500'>Footer • {"{{1}}"} {"{{2}}"}</p>
        <div className='mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700'><MessageCircleMore size={12} />Botão de ação</div>
      </div>
    </div>
    <div className='mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500'>
      <span className='inline-flex items-center gap-1'><CalendarDays size={12} />Criado em {toLocalDate(t.created_at)}</span>
      <span>Provider associado: {t.provider_id || 'N/D'}</span>
    </div>
    <button disabled={loading} className='secondary-button mt-3 border border-slate-300 bg-white hover:bg-slate-100' onClick={onSubmit}>Enviar para aprovação</button>
  </article>;
}
