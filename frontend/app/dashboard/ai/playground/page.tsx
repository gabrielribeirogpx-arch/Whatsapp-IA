'use client';

import { useEffect, useMemo, useState } from 'react';
import { getAIExecution, listAIExecutions, type AIExecution, type AIExecutionsResponse } from '@/lib/api';

const nodeTypes = ['ai_response', 'ai_rag', 'ai_classification', 'ai_extraction', 'ai_summary'];
const statuses = ['success', 'error'];

type Filters = {
  flow_id?: string;
  conversation_id?: string;
  session_id?: string;
  node_type?: string;
  provider?: string;
  model?: string;
  status?: string;
  fallback?: string;
  confidence_min?: string;
  confidence_max?: string;
  date_from?: string;
  date_to?: string;
};

function asText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function pct(value: number | null | undefined): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}

export default function AIPlaygroundPage() {
  const [data, setData] = useState<AIExecutionsResponse | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AIExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const query = useMemo(() => ({ ...filters, fallback: filters.fallback === '' ? undefined : filters.fallback, page, page_size: 25 }), [filters, page]);

  async function load() {
    setLoading(true);
    try {
      setData(await listAIExecutions(query));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [query]);

  async function openDetails(item: AIExecution) {
    setSelected(await getAIExecution(item.id));
  }

  const metrics = data?.metrics;
  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / 25));

  return (
    <div className="min-h-screen bg-slate-50 p-8 text-slate-900">
      <div className="mb-6">
        <p className="text-sm font-semibold uppercase tracking-wide text-emerald-600">Dashboard → IA</p>
        <h1 className="text-3xl font-bold">Playground de IA</h1>
        <p className="mt-2 text-sm text-slate-500">Observabilidade segura das execuções de IA. Prompts completos, API keys, chunks integrais e vetores não são exibidos.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        {[
          ['Execuções hoje', metrics?.today ?? 0],
          ['Latência média', `${metrics?.avg_latency_ms ?? 0} ms`],
          ['Fallback %', `${metrics?.fallback_percent ?? 0}%`],
          ['Confidence média', metrics?.avg_confidence ?? '—'],
          ['Top providers', metrics?.top_providers?.map((x) => `${x.name} (${x.count})`).join(', ') || '—'],
          ['Top models', metrics?.top_models?.map((x) => `${x.name} (${x.count})`).join(', ') || '—'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase text-slate-500">{label}</p>
            <p className="mt-2 text-lg font-bold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-6">
          {(['flow_id', 'conversation_id', 'session_id', 'provider', 'model'] as const).map((key) => (
            <input key={key} className="rounded-xl border border-slate-200 px-3 py-2 text-sm" placeholder={key} value={filters[key] || ''} onChange={(e) => { setPage(1); setFilters({ ...filters, [key]: e.target.value }); }} />
          ))}
          <select className="rounded-xl border border-slate-200 px-3 py-2 text-sm" value={filters.node_type || ''} onChange={(e) => { setPage(1); setFilters({ ...filters, node_type: e.target.value }); }}>
            <option value="">Node Type</option>{nodeTypes.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <select className="rounded-xl border border-slate-200 px-3 py-2 text-sm" value={filters.status || ''} onChange={(e) => { setPage(1); setFilters({ ...filters, status: e.target.value }); }}>
            <option value="">Status</option>{statuses.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <select className="rounded-xl border border-slate-200 px-3 py-2 text-sm" value={filters.fallback || ''} onChange={(e) => { setPage(1); setFilters({ ...filters, fallback: e.target.value }); }}>
            <option value="">Fallback</option><option value="true">Sim</option><option value="false">Não</option>
          </select>
          <input className="rounded-xl border border-slate-200 px-3 py-2 text-sm" placeholder="Confidence min" value={filters.confidence_min || ''} onChange={(e) => setFilters({ ...filters, confidence_min: e.target.value })} />
          <input className="rounded-xl border border-slate-200 px-3 py-2 text-sm" placeholder="Confidence max" value={filters.confidence_max || ''} onChange={(e) => setFilters({ ...filters, confidence_max: e.target.value })} />
          <input type="datetime-local" className="rounded-xl border border-slate-200 px-3 py-2 text-sm" value={filters.date_from || ''} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} />
          <input type="datetime-local" className="rounded-xl border border-slate-200 px-3 py-2 text-sm" value={filters.date_to || ''} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} />
        </div>
      </div>

      <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-100 text-xs uppercase text-slate-500"><tr>{['Data','Node','Modelo','Tempo','Status','Provider','Confidence','Fallback','Retrieval'].map((h) => <th key={h} className="px-4 py-3">{h}</th>)}</tr></thead>
          <tbody>
            {loading ? <tr><td className="px-4 py-8 text-center" colSpan={9}>Carregando...</td></tr> : data?.items.map((item) => (
              <tr key={item.id} onClick={() => void openDetails(item)} className="cursor-pointer border-t border-slate-100 hover:bg-emerald-50/50">
                <td className="px-4 py-3">{new Date(item.created_at).toLocaleString()}</td><td className="px-4 py-3 font-semibold">{item.node_type}<br/><span className="text-xs text-slate-400">{item.node_id}</span></td><td className="px-4 py-3">{item.model || '—'}</td><td className="px-4 py-3">{item.latency_ms ?? '—'} ms</td><td className="px-4 py-3">{item.status}</td><td className="px-4 py-3">{item.provider || '—'}</td><td className="px-4 py-3">{pct(item.confidence)}</td><td className="px-4 py-3">{item.fallback_used ? 'Sim' : 'Não'}</td><td className="px-4 py-3">{item.retrieval_mode || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm text-slate-600"><span>Total: {data?.total || 0}</span><div className="flex gap-2"><button className="rounded-lg border px-3 py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button><span className="px-2 py-1">{page}/{totalPages}</span><button className="rounded-lg border px-3 py-1" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Próxima</button></div></div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 bg-slate-900/30" onClick={() => setSelected(null)}>
          <aside className="ml-auto h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <button className="mb-4 rounded-lg border px-3 py-1 text-sm" onClick={() => setSelected(null)}>Fechar</button>
            <h2 className="text-2xl font-bold">Execução IA</h2>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              {[
                ['Node', `${selected.node_type} / ${selected.node_id}`], ['Provider', selected.provider], ['Modelo', selected.model], ['Latência', `${selected.latency_ms ?? '—'} ms`], ['Retrieval mode', selected.retrieval_mode], ['Confidence', pct(selected.confidence)], ['Fallback', selected.fallback_used ? 'Sim' : 'Não'], ['Tempo total', `${selected.latency_ms ?? '—'} ms`], ['Tokens', selected.total_tokens ?? '—']
              ].map(([k,v]) => <div key={k} className="rounded-xl bg-slate-50 p-3"><p className="text-xs font-semibold uppercase text-slate-500">{k}</p><p className="mt-1 font-semibold">{asText(v)}</p></div>)}
            </div>
            <section className="mt-6 space-y-4 text-sm">
              <div><h3 className="font-bold">Prompt resumido</h3><pre className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-3">{asText(selected.metadata.prompt_summary)}</pre></div>
              <div><h3 className="font-bold">Pergunta original</h3><p className="mt-2 rounded-xl bg-slate-50 p-3">{asText(selected.metadata.original_question)}</p></div>
              <div><h3 className="font-bold">Pergunta standalone</h3><p className="mt-2 rounded-xl bg-slate-50 p-3">{asText(selected.metadata.standalone_question)}</p></div>
              <div><h3 className="font-bold">Chunks</h3><div className="mt-2 space-y-2">{Array.isArray(selected.metadata.chunks) && selected.metadata.chunks.length ? selected.metadata.chunks.map((chunk, i) => <pre key={i} className="rounded-xl bg-slate-50 p-3">{asText(chunk)}</pre>) : <p className="rounded-xl bg-slate-50 p-3">Nenhum chunk registrado.</p>}</div></div>
              <div><h3 className="font-bold">Metadata segura</h3><pre className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-3">{JSON.stringify(selected.metadata, null, 2)}</pre></div>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
