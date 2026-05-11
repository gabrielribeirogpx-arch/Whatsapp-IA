import { Activity, Building2, Cable, Signal } from 'lucide-react';
import { StatusBadge, toLocalDate } from './ui';

export default function ProviderCard({ p, onTest, onActivate, onDelete, loading }: { p: any; onTest: any; onActivate: any; onDelete: any; loading: boolean }) {
  return <article className={`group rounded-2xl border p-4 transition-all duration-300 ${p.status === 'connected' ? 'border-emerald-200/80 bg-gradient-to-b from-white to-emerald-50/40 shadow-[0_18px_34px_-28px_rgba(16,185,129,0.5)]' : 'border-slate-200/80 bg-gradient-to-b from-white to-slate-50/60 shadow-[0_16px_30px_-28px_rgba(15,23,42,0.8)]'} hover:-translate-y-0.5 hover:shadow-[0_24px_40px_-30px_rgba(15,23,42,0.75)]`}>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div className='space-y-2'>
        <p className='inline-flex items-center gap-2 text-sm font-semibold text-slate-900'><span className='rounded-xl border border-emerald-200 bg-emerald-50 p-2 text-emerald-700'><Cable size={14} /></span>{p.display_name || p.provider_type}</p>
        <div className='flex flex-wrap gap-2'><StatusBadge value={p.status} /><StatusBadge value={p.is_active ? 'active' : 'inactive'} /></div>
      </div>
      <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${p.status === 'connected' ? 'border-emerald-300/70 bg-gradient-to-r from-emerald-100 to-emerald-50 text-emerald-700' : 'border-amber-200 bg-gradient-to-r from-amber-100 to-amber-50 text-amber-700'}`}><Activity size={12} />Health {p.status === 'connected' ? 'ok' : 'degraded'}</span>
    </div>
    <div className='mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-3'>
      <span className='inline-flex items-center gap-1'><Building2 size={12} />Tipo: {p.provider_type}</span>
      <span className='inline-flex items-center gap-1'><Signal size={12} />Último sync: {toLocalDate(p.updated_at)}</span>
      <span>WABA: {p.waba_id || '—'}</span>
    </div>
    <div className='mt-4 flex flex-wrap gap-2'>
      <button disabled={loading} className='secondary-button border border-slate-300 bg-white/90 hover:bg-slate-100' onClick={onTest}>Testar</button>
      <button disabled={loading} className='secondary-button border border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100' onClick={onActivate}>{p.is_active ? 'Ativo' : 'Ativar'}</button>
      <button disabled={loading} className='secondary-button border border-slate-300 bg-white/90 hover:bg-slate-100'>Editar</button>
      <button disabled={loading} className='secondary-button border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100' onClick={onDelete}>Remover</button>
    </div>
  </article>;
}
