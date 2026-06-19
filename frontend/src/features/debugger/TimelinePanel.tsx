'use client';

export type ReplayEvent = {
  event_type: string;
  timestamp?: string | null;
  execution_id?: string | null;
  node_id?: string | null;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
};

function formatDate(value?: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString('pt-BR');
}

export function TimelinePanel({ timeline }: { timeline: ReplayEvent[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Timeline cronológica</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">{timeline.length} eventos</span>
      </div>
      <ol className="space-y-3">
        {timeline.map((event, index) => {
          const failed = event.event_type.includes('FAILED');
          return (
            <li key={`${event.event_type}-${event.timestamp}-${index}`} className={`rounded-xl border p-3 ${failed ? 'border-rose-300 bg-rose-50' : 'border-slate-200 bg-slate-50'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${failed ? 'bg-rose-600 text-white' : 'bg-slate-900 text-white'}`}>{event.event_type}</span>
                {event.node_id && <span className="text-sm font-medium text-slate-700">Nó: {event.node_id}</span>}
                <span className="text-xs text-slate-500">{formatDate(event.timestamp)}</span>
              </div>
              {event.duration_ms !== null && event.duration_ms !== undefined && <p className="mt-2 text-xs text-slate-500">Duração: {event.duration_ms}ms</p>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
