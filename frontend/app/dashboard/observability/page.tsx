'use client';

import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, RefreshCw, Search } from 'lucide-react';
import { apiFetch } from '@/lib/api';

type Overview = { messages_received: number; messages_sent: number; executions: number; errors: number; retries: number; success_rate: number; latency: { p50: number | null; p95: number | null; p99: number | null } };
type Trace = { id: string; trace_id: string; execution_id: string; event_type: string; timestamp: string; duration_ms: number | null; metadata: Record<string, unknown> };
const empty: Overview = { messages_received: 0, messages_sent: 0, executions: 0, errors: 0, retries: 0, success_rate: 100, latency: { p50: null, p95: null, p99: null } };

export default function ObservabilityPage() {
  const [overview, setOverview] = useState<Overview>(empty); const [traces, setTraces] = useState<Trace[]>([]);
  const [selected, setSelected] = useState<Trace[] | null>(null); const [query, setQuery] = useState(''); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async () => { setLoading(true); setError(''); try {
    const [summary, list] = await Promise.all([apiFetch('/api/observability/overview?hours=24'), apiFetch('/api/observability/traces?hours=24&page_size=30')]);
    if (!summary.ok || !list.ok) throw new Error('Não foi possível carregar os dados de observabilidade.');
    setOverview(await summary.json()); setTraces((await list.json()).items || []);
  } catch (e) { setError(e instanceof Error ? e.message : 'Erro inesperado'); } finally { setLoading(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  const openTrace = async (traceId: string) => { const response = await apiFetch(`/api/observability/traces/${encodeURIComponent(traceId)}`); if (response.ok) setSelected((await response.json()).events || []); };
  const shown = traces.filter((item) => !query || item.trace_id.includes(query) || item.execution_id.includes(query) || item.event_type.includes(query.toUpperCase()));
  const cards = [['Recebidas', overview.messages_received, Activity], ['Enviadas', overview.messages_sent, CheckCircle2], ['Execuções', overview.executions, Activity], ['Erros', overview.errors, AlertTriangle], ['Retries', overview.retries, RefreshCw], ['p95 resposta', overview.latency.p95 == null ? '—' : `${overview.latency.p95} ms`, Clock3]] as const;
  return <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-7">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-sm font-semibold text-emerald-600">OPERAÇÕES</p><h1 className="text-2xl font-bold text-slate-900">Observabilidade</h1><p className="mt-1 text-sm text-slate-500">Traces e eventos reais das últimas 24 horas. Conteúdo sensível é mascarado.</p></div><button onClick={() => void load()} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium"><RefreshCw size={15}/>Atualizar</button></header>
    {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">{cards.map(([label, value, Icon]) => <article key={label} className="rounded-xl border border-slate-200 bg-white p-4"><Icon size={17} className="mb-3 text-emerald-600"/><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{loading ? '…' : value}</p></article>)}</section>
    <section className="rounded-xl border border-slate-200 bg-white"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4"><div><h2 className="font-semibold text-slate-900">Traces recentes</h2><p className="text-xs text-slate-500">Clique para abrir o replay somente leitura.</p></div><label className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5"><Search size={15}/><input aria-label="Filtrar traces" value={query} onChange={(e) => setQuery(e.target.value)} className="w-44 text-sm outline-none" placeholder="Trace, execução ou evento"/></label></div>
      <div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="p-3">Trace</th><th>Evento</th><th>Quando</th><th>Duração</th><th></th></tr></thead><tbody>{shown.map((trace) => <tr key={trace.id} className="border-t border-slate-100"><td className="p-3 font-mono text-xs">{trace.trace_id.slice(0, 16)}…</td><td>{trace.event_type}</td><td>{new Date(trace.timestamp).toLocaleString('pt-BR')}</td><td>{trace.duration_ms == null ? '—' : `${trace.duration_ms} ms`}</td><td><button onClick={() => void openTrace(trace.trace_id)} className="text-sm font-medium text-emerald-700">Timeline</button></td></tr>)}{!loading && !shown.length && <tr><td className="p-7 text-center text-slate-500" colSpan={5}>Nenhum evento para o período selecionado.</td></tr>}</tbody></table></div></section>
    {selected && <aside className="fixed inset-y-0 right-0 z-50 w-full max-w-xl overflow-y-auto border-l border-slate-200 bg-white p-5 shadow-xl"><div className="flex items-center justify-between"><h2 className="font-bold text-slate-900">Replay do trace</h2><button onClick={() => setSelected(null)} className="text-sm text-slate-500">Fechar</button></div><p className="mt-1 text-xs text-slate-500">Inspeção somente leitura: nenhuma ação externa será executada.</p><ol className="mt-6 space-y-4 border-l border-emerald-200 pl-5">{selected.map((event, index) => <li key={event.id} className="relative"><i className="absolute -left-[25px] top-1 h-3 w-3 rounded-full bg-emerald-500"/><p className="font-medium text-slate-900">{index + 1}. {event.event_type}</p><p className="text-xs text-slate-500">{new Date(event.timestamp).toLocaleString('pt-BR')} · {event.duration_ms ?? '—'} ms</p><pre className="mt-1 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-600">{JSON.stringify(event.metadata, null, 2)}</pre></li>)}</ol></aside>}
  </main>;
}
