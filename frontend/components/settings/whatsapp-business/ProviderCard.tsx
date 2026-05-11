import { Activity, Building2, Cable, Signal } from 'lucide-react';
import { StatusBadge, toLocalDate } from './ui';

function qualityColor(quality?: string) {
  if (quality === 'GREEN') return 'text-emerald-700 bg-emerald-100 border-emerald-300';
  if (quality === 'YELLOW') return 'text-amber-700 bg-amber-100 border-amber-300';
  if (quality === 'RED') return 'text-rose-700 bg-rose-100 border-rose-300';
  return 'text-slate-600 bg-slate-100 border-slate-300';
}

export default function ProviderCard({ p, onTest, onActivate, onDelete, loading }: { p: any; onTest: any; onActivate: any; onDelete: any; loading: boolean }) {
  const meta = p.metadata_json || {};
  const quality = meta.quality_rating;
  return <article className={`group w-full min-w-0 rounded-2xl border p-4 transition-all duration-300 ${p.status === 'connected' ? 'border-emerald-200/80 bg-gradient-to-b from-white to-emerald-50/40 shadow-[0_18px_34px_-28px_rgba(16,185,129,0.5)]' : 'border-slate-200/80 bg-gradient-to-b from-white to-slate-50/60 shadow-[0_16px_30px_-28px_rgba(15,23,42,0.8)]'} hover:-translate-y-0.5 hover:shadow-[0_24px_40px_-30px_rgba(15,23,42,0.75)]`}>
    <div className='flex flex-wrap items-start justify-between gap-3'>
      <div className='space-y-2'>
        <p className='inline-flex items-center gap-2 text-sm font-semibold text-slate-900'><span className='rounded-xl border border-emerald-200 bg-emerald-50 p-2 text-emerald-700'><Cable size={14} /></span>{p.display_name || p.provider_type}</p>
        <div className='flex flex-wrap gap-2'><StatusBadge value={p.status} /><StatusBadge value={p.is_active ? 'active' : 'inactive'} /></div>
      </div>
      <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${qualityColor(quality)}`}><Activity size={12} />Quality {quality || 'N/A'}</span>
    </div>
    <div className='mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-3'>
      <span className='inline-flex items-center gap-1'><Building2 size={12} />Meta: {meta.verified_name || '—'}</span>
      <span className='inline-flex items-center gap-1'><Signal size={12} />Último sync: {toLocalDate(meta.last_sync_at || p.last_connection_check_at || p.updated_at)}</span>
      <span>Número: {meta.display_phone_number || p.phone_number_id || '—'}</span>
    </div>
    <div className='mt-4 flex flex-wrap gap-2'>
      <button disabled={loading} className='secondary-button border border-slate-300 bg-white/90 hover:bg-slate-100' onClick={onTest}>Testar</button>
      <button disabled={loading} className='secondary-button border border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100' onClick={onActivate}>{p.is_active ? 'Ativo' : 'Ativar'}</button>
      <button disabled={loading} className='secondary-button border border-slate-300 bg-white/90 hover:bg-slate-100'>Editar</button>
      <button disabled={loading} className='secondary-button border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100' onClick={onDelete}>Remover</button>
    </div>
  </article>;
}
