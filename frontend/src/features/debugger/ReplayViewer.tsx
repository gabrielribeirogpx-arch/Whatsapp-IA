'use client';

import { ExecutionPathPanel, ReplayNode } from './ExecutionPathPanel';
import { ReplayEvent, TimelinePanel } from './TimelinePanel';

export type ReplayEdge = { source: string; target: string; highlighted?: boolean; execution_id?: string | null; order?: number | null };
export type ReplayExecution = {
  trace_id: string;
  flow_id?: string | null;
  conversation_id?: string | null;
  contact_id?: string | null;
  tenant_id?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  duration_ms: number;
  nodes: ReplayNode[];
  edges: ReplayEdge[];
  timeline: ReplayEvent[];
};

export function ReplayViewer({ replay }: { replay: ReplayExecution }) {
  const failures = replay.nodes.filter((node) => node.status === 'failed').length;
  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Replay / Visual Flow Debugger</p>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-950">Trace {replay.trace_id}</h1>
            <p className="text-sm text-slate-500">{replay.nodes.length} nós · {replay.edges.length} edges · {replay.duration_ms}ms</p>
          </div>
          <span className={`rounded-full px-3 py-1 text-sm font-semibold ${failures ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'}`}>{failures ? `${failures} falha(s)` : 'Sem falhas'}</span>
        </div>
      </header>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <TimelinePanel timeline={replay.timeline} />
        <ExecutionPathPanel nodes={replay.nodes} />
      </div>
    </div>
  );
}
