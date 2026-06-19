'use client';

export type ReplayNode = {
  node_id: string;
  node_name?: string | null;
  node_type?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  status: string;
};

export function ExecutionPathPanel({ nodes }: { nodes: ReplayNode[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Caminho executado</h2>
      <div className="space-y-3">
        {nodes.map((node, index) => {
          const failed = node.status === 'failed';
          return (
            <div key={`${node.node_id}-${index}`} className={`flex items-center gap-3 rounded-xl border p-3 ${failed ? 'border-rose-300 bg-rose-50' : 'border-emerald-200 bg-emerald-50/60'}`}>
              <span className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${failed ? 'bg-rose-600 text-white' : 'bg-emerald-600 text-white'}`}>{index + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-slate-900">{node.node_name || node.node_id}</p>
                <p className="text-xs text-slate-500">{node.node_type || 'tipo desconhecido'} · {node.duration_ms ?? 0}ms</p>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${failed ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'}`}>{node.status}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
