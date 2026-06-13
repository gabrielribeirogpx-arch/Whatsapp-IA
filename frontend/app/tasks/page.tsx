'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { completeTask, listTasks, updateTask, type TaskFilters } from '../../lib/api';
import { TaskItem } from '../../lib/types';
import { useRealtime } from '../../hooks/useRealtime';

type FilterKey = 'all' | 'open' | 'in_progress' | 'completed' | 'overdue';

const filters: Array<{ key: FilterKey; label: string; query: TaskFilters }> = [
  { key: 'all', label: 'Todas', query: {} },
  { key: 'open', label: 'Abertas', query: { status: 'open' } },
  { key: 'in_progress', label: 'Em andamento', query: { status: 'in_progress' } },
  { key: 'completed', label: 'Concluídas', query: { status: 'completed' } },
  { key: 'overdue', label: 'Atrasadas', query: { overdue: true } }
];

const statusLabels: Record<string, string> = {
  open: 'Aberta',
  in_progress: 'Em andamento',
  completed: 'Concluída'
};

const priorityLabels: Record<string, string> = {
  low: 'Baixa',
  normal: 'Normal',
  high: 'Alta',
  urgent: 'Urgente'
};

function taskMatchesSearch(task: TaskItem, search: string) {
  const normalized = search.trim().toLowerCase();
  if (!normalized) return true;
  return [
    task.title,
    task.description,
    task.contact_name,
    task.contact_phone,
    task.conversation_name,
    task.conversation_phone,
    task.assigned_to
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

function formatDate(value?: string | null) {
  if (!value) return 'Sem prazo';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Sem prazo';
  return date.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function chatHref(task: TaskItem) {
  if (task.conversation_id) return `/chat?conversation_id=${encodeURIComponent(task.conversation_id)}`;
  if (task.conversation_phone) return `/chat?phone=${encodeURIComponent(task.conversation_phone)}`;
  return '/chat';
}

export default function TasksPage() {
  const [activeFilter, setActiveFilter] = useState<FilterKey>('all');
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  const selectedFilter = filters.find((item) => item.key === activeFilter) ?? filters[0];

  const load = useCallback(async () => {
    const data = await listTasks(selectedFilter.query);
    setTasks(data);
  }, [selectedFilter]);

  useEffect(() => {
    setLoading(true);
    load()
      .catch(() => setError('Falha ao carregar tarefas.'))
      .finally(() => setLoading(false));
  }, [load]);

  useRealtime({
    wsUrl: `${process.env.NEXT_PUBLIC_API_URL?.replace(/^https/, 'wss').replace(/^http/, 'ws')}/api/dashboard/ws`,
    sseUrl: `${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/stream`,
    tenantId: typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || '' : '',
    onMessage: (payload: { event?: string; type?: string; action?: string }) => {
      const type = String(payload.event || payload.type || payload.action || '').toLowerCase();
      if (['task_created', 'task_updated', 'task_completed'].includes(type) || payload.action?.startsWith('TASK_')) {
        load().catch(() => undefined);
      }
    }
  });

  const visibleTasks = useMemo(() => tasks.filter((task) => taskMatchesSearch(task, search)), [tasks, search]);

  const startTask = async (task: TaskItem) => {
    setSavingId(task.id);
    try {
      const updated = await updateTask(task.id, { status: 'in_progress' });
      setTasks((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch {
      setError('Falha ao iniciar tarefa.');
    } finally {
      setSavingId(null);
    }
  };

  const finishTask = async (task: TaskItem) => {
    setSavingId(task.id);
    try {
      const updated = await completeTask(task.id);
      setTasks((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch {
      setError('Falha ao concluir tarefa.');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 p-6 text-slate-900">
      <section className="mx-auto flex max-w-6xl flex-col gap-6">
        <div className="flex flex-col justify-between gap-4 rounded-3xl bg-white p-6 shadow-sm md:flex-row md:items-center">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-emerald-600">Wazza</p>
            <h1 className="text-3xl font-bold">Tarefas</h1>
            <p className="mt-2 text-sm text-slate-500">Acompanhe tarefas criadas pelos flows e mantenha o atendimento em dia.</p>
          </div>
          <Link href="/chat" className="rounded-2xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700">Abrir Inbox</Link>
        </div>

        <div className="rounded-3xl bg-white p-4 shadow-sm">
          <div className="flex flex-wrap gap-2">
            {filters.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setActiveFilter(filter.key)}
                className={`rounded-full px-4 py-2 text-sm font-semibold ${activeFilter === filter.key ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar por título, descrição ou contato"
            className="mt-4 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-emerald-500"
          />
        </div>

        {error ? <p className="rounded-2xl bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
        {loading ? <p className="rounded-3xl bg-white p-6 text-sm text-slate-500 shadow-sm">Carregando tarefas...</p> : null}
        {!loading && !visibleTasks.length ? <p className="rounded-3xl bg-white p-6 text-sm text-slate-500 shadow-sm">Nenhuma tarefa encontrada.</p> : null}

        <section className="grid gap-4 md:grid-cols-2">
          {visibleTasks.map((task) => {
            const isDone = task.status === 'completed';
            return (
              <article key={task.id} className="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-bold text-slate-950">{task.title}</h2>
                    <p className="mt-1 text-sm text-slate-500">{task.description || 'Sem descrição'}</p>
                  </div>
                  <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">{priorityLabels[task.priority] || task.priority}</span>
                </div>
                <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-slate-400">Responsável</dt><dd className="font-semibold">{task.assigned_to || 'Não atribuído'}</dd></div>
                  <div><dt className="text-slate-400">Prazo</dt><dd className="font-semibold">{formatDate(task.due_at)}</dd></div>
                  <div><dt className="text-slate-400">Status</dt><dd className="font-semibold">{statusLabels[task.status] || task.status}</dd></div>
                  <div><dt className="text-slate-400">Contato/conversa</dt><dd className="font-semibold">{task.contact_name || task.conversation_name || task.contact_phone || task.conversation_phone || '-'}</dd></div>
                </dl>
                <div className="mt-5 flex flex-wrap gap-2">
                  <Link href={chatHref(task)} className="rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Abrir conversa</Link>
                  <button type="button" disabled={isDone || savingId === task.id} onClick={() => startTask(task)} className="rounded-xl border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 disabled:opacity-50">Iniciar</button>
                  <button type="button" disabled={isDone || savingId === task.id} onClick={() => finishTask(task)} className="rounded-xl bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Concluir</button>
                </div>
              </article>
            );
          })}
        </section>
      </section>
    </main>
  );
}
