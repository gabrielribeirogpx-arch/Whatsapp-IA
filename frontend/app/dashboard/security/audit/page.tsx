'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Clock3, Filter, Search, ShieldCheck } from 'lucide-react';
import { listAuditLogs } from '@/lib/api';
import { AuditLog } from '@/lib/types';

const actionLabels: Record<string, string> = {
  LOGIN_SUCCESS: 'Login bem-sucedido',
  LOGIN_FAILED: 'Login falhou',
  PASSWORD_CHANGED: 'Senha alterada',
  PASSWORD_RESET_REQUESTED: 'Reset solicitado',
  PASSWORD_RESET_COMPLETED: 'Reset concluído',
  FLOW_CREATED: 'Fluxo criado',
  FLOW_UPDATED: 'Fluxo atualizado',
  FLOW_PUBLISHED: 'Fluxo publicado',
  FLOW_DELETED: 'Fluxo excluído',
  USER_CREATED: 'Usuário criado',
  USER_UPDATED: 'Usuário atualizado',
  USER_DISABLED: 'Usuário desativado',
  WHATSAPP_PROVIDER_UPDATED: 'Provider WhatsApp atualizado',
  API_KEY_UPDATED: 'API key atualizada',
  SESSION_REVOKED: 'Sessão encerrada'
};

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('pt-BR') : 'Sem data';
}

function actionTone(action: string) {
  if (action.includes('FAILED') || action.includes('DELETED') || action.includes('DISABLED')) return 'border-rose-200 bg-rose-50 text-rose-700';
  if (action.includes('PASSWORD') || action.includes('API_KEY') || action.includes('SESSION')) return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700';
}

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ user_id: '', action: '', start_date: '', end_date: '' });

  const load = async () => {
    setLoading(true);
    try {
      const data = await listAuditLogs({
        user_id: filters.user_id || undefined,
        action: filters.action || undefined,
        start_date: filters.start_date ? new Date(filters.start_date).toISOString() : undefined,
        end_date: filters.end_date ? new Date(`${filters.end_date}T23:59:59`).toISOString() : undefined
      });
      setLogs(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const actions = useMemo(() => Object.keys(actionLabels).sort(), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    load();
  };

  return (
    <main className='space-y-6 p-5 md:p-8'>
      <header className='relative overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-gradient-to-br from-slate-950 via-slate-900 to-emerald-950 p-6 text-white shadow-[0_24px_60px_-36px_rgba(2,6,23,0.8)] md:p-8'>
        <div className='pointer-events-none absolute right-10 top-6 h-32 w-32 rounded-full bg-emerald-400/20 blur-3xl' />
        <p className='inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-semibold text-emerald-100'><ShieldCheck size={14} /> Enterprise Audit Trail</p>
        <h1 className='mt-4 text-3xl font-semibold tracking-tight'>Auditoria de segurança</h1>
        <p className='mt-2 max-w-3xl text-sm leading-relaxed text-slate-300'>Trilha real de eventos críticos por tenant, usuário, IP e metadata para demonstrações enterprise, licitações e investigações operacionais.</p>
      </header>

      <form onSubmit={submit} className='grid gap-3 rounded-3xl border border-[color:var(--surface-border)] bg-white/95 p-4 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)] md:grid-cols-[1fr_220px_180px_180px_auto]'>
        <label className='block'><span className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-500'>Usuário</span><input value={filters.user_id} onChange={e => setFilters(p => ({ ...p, user_id: e.target.value }))} placeholder='UUID do usuário' className='mt-2 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100' /></label>
        <label className='block'><span className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-500'>Ação</span><select value={filters.action} onChange={e => setFilters(p => ({ ...p, action: e.target.value }))} className='mt-2 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100'><option value=''>Todas</option>{actions.map(action => <option key={action} value={action}>{action}</option>)}</select></label>
        <label className='block'><span className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-500'>Início</span><input type='date' value={filters.start_date} onChange={e => setFilters(p => ({ ...p, start_date: e.target.value }))} className='mt-2 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100' /></label>
        <label className='block'><span className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-500'>Fim</span><input type='date' value={filters.end_date} onChange={e => setFilters(p => ({ ...p, end_date: e.target.value }))} className='mt-2 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100' /></label>
        <button className='mt-6 inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white'><Filter size={16} /> Filtrar</button>
      </form>

      <section className='overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-white/95 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)]'>
        <div className='flex items-center justify-between border-b border-slate-100 p-5'>
          <div><h2 className='text-lg font-semibold text-slate-950'>Eventos registrados</h2><p className='text-sm text-slate-500'>{loading ? 'Carregando...' : `${logs.length} evento(s) encontrados`}</p></div>
          <Search className='text-slate-400' size={20} />
        </div>
        <div className='overflow-x-auto'>
          <table className='min-w-full divide-y divide-slate-100 text-left text-sm'>
            <thead className='bg-slate-50 text-xs uppercase tracking-[0.14em] text-slate-500'><tr><th className='px-5 py-3'>Usuário</th><th className='px-5 py-3'>Ação</th><th className='px-5 py-3'>Data</th><th className='px-5 py-3'>IP</th><th className='px-5 py-3'>Detalhes</th></tr></thead>
            <tbody className='divide-y divide-slate-100'>
              {logs.map(log => <tr key={log.id} className='align-top hover:bg-slate-50/70'><td className='px-5 py-4'><p className='font-semibold text-slate-950'>{log.user_name || 'Sistema'}</p><p className='text-xs text-slate-500'>{log.user_email || log.user_id || 'Sem usuário vinculado'}</p></td><td className='px-5 py-4'><span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${actionTone(log.action)}`}>{actionLabels[log.action] || log.action}</span><p className='mt-1 text-xs text-slate-400'>{log.action}</p></td><td className='px-5 py-4 text-slate-600'><span className='inline-flex items-center gap-2'><Clock3 size={14} /> {fmtDate(log.created_at)}</span></td><td className='px-5 py-4 font-mono text-xs text-slate-600'>{log.ip_address || '—'}</td><td className='px-5 py-4'><p className='text-xs font-semibold text-slate-500'>{log.entity_type || 'evento'} {log.entity_id ? `· ${log.entity_id}` : ''}</p><pre className='mt-2 max-w-md overflow-auto rounded-2xl bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100'>{JSON.stringify(log.metadata_json || {}, null, 2)}</pre></td></tr>)}
              {!loading && logs.length === 0 && <tr><td colSpan={5} className='px-5 py-12 text-center text-sm text-slate-500'>Nenhum evento encontrado para os filtros selecionados.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
