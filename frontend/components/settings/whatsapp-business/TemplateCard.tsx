import { CalendarDays, MessageCircleMore } from 'lucide-react';
import { ClientDateTime, StatusBadge } from './ui';
import { renderExample } from '@/lib/templateVariableMapper';

export default function TemplateCard({ t, onSubmit, loading }: { t: any; onSubmit: any; loading: boolean }) {
  return <article className='w-full min-w-0 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-4 shadow-[0_16px_30px_-28px_rgba(15,23,42,0.8)] transition-all duration-300 hover:-translate-y-0.5 hover:border-emerald-200 hover:shadow-[0_24px_40px_-30px_rgba(15,23,42,0.75)]'>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div>
        <p className='text-sm font-semibold text-slate-900'>{t.name}</p>
        <p className='mt-1 text-xs text-slate-500'>{t.category} · {t.language}</p>
      </div>
      <StatusBadge value={t.status} />
    </div>
    <div className='mt-3 rounded-2xl border border-emerald-100/80 bg-[#e8f4ec] p-3'>
      <div className='mb-2 text-[11px] font-medium text-emerald-900'>Preview WhatsApp</div>
      <div className='relative overflow-hidden rounded-2xl border border-emerald-200/60 bg-[#efeae2] p-3 text-sm shadow-inner'>
        <div className='absolute inset-0 opacity-40' style={{ backgroundImage: 'radial-gradient(circle at 25% 25%, #ffffff 1px, transparent 1px)', backgroundSize: '18px 18px' }} />
        <div className='relative mb-3 flex items-center gap-2 text-xs text-slate-600'><span className='inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-[10px] font-semibold text-white'>B</span><span className='font-medium'>Business</span><span className='ml-auto'>09:41</span></div>
        <div className='relative ml-auto max-w-[92%] rounded-2xl rounded-tr-sm bg-[#dcf8c6] px-3 py-2.5 text-slate-800 shadow-sm'>
          <p className='text-[13px] leading-relaxed'>{renderExample(t.body_text || '', t.variables_json).slice(0, 140) || 'Mensagem do template...'}</p>
          <p className='mt-1 text-right text-[10px] text-slate-500'>09:41 ✓✓</p>
        </div>
        <div className='relative mt-2 inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-white/90 px-2.5 py-1 text-xs text-emerald-700'><MessageCircleMore size={12} />Botão de ação</div>
      </div>
    </div>
    <div className='mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500'>
      <span className='inline-flex items-center gap-1'><CalendarDays size={12} />Criado em <ClientDateTime value={t.created_at} /></span>
      <span>Provider associado: {t.provider_id || 'N/D'}</span>
    </div>
    <button disabled={loading} className='secondary-button mt-3 border border-slate-300 bg-white hover:bg-slate-100' onClick={onSubmit}>Enviar para aprovação</button>
  </article>;
}
