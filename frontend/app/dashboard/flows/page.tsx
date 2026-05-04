'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { createFlow, deleteFlow, duplicateFlow, listFlows, updateFlow, updateFlowStatus } from '@/lib/api';
import { FlowItem, FlowPayload } from '@/lib/types';

type FlowListItem = FlowItem & {
  status?: string;
  is_published?: boolean;
  executions?: number;
  conversion_rate?: number;
};

const getUpdatedLabel = (updatedAt?: string | null) => {
  if (!updatedAt) return 'Atualizado recentemente';
  const updatedTime = new Date(updatedAt).getTime();
  if (Number.isNaN(updatedTime)) return 'Atualizado recentemente';

  const diffMs = Date.now() - updatedTime;
  if (diffMs <= 0) return 'Atualizado recentemente';

  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  if (hours < 24) return `Atualizado há ${hours} hora${hours === 1 ? '' : 's'}`;

  const days = Math.floor(hours / 24);
  return `Atualizado há ${days} dia${days === 1 ? '' : 's'}`;
};

const getFlowExecutions = (flow: FlowListItem) => {
  const metrics = flow as unknown as Record<string, unknown>;
  const candidates = [metrics.executions, metrics.execution_count, metrics.entries, metrics.total_executions];
  const value = candidates.find((candidate) => typeof candidate === 'number' && Number.isFinite(candidate));
  return typeof value === 'number' ? value : null;
};

const getFlowConversion = (flow: FlowListItem) => {
  const metrics = flow as unknown as Record<string, unknown>;
  const candidates = [metrics.conversion_rate, metrics.conversion, metrics.conversionPercent, metrics.completed_rate];
  const value = candidates.find((candidate) => typeof candidate === 'number' && Number.isFinite(candidate));
  return typeof value === 'number' ? value : null;
};

const getFlowIdHash = (flowId: string) => {
  return Array.from(flowId).reduce((hash, char) => ((hash * 31) + char.charCodeAt(0)) % 1000003, 7);
};

const getMockExecutions = (flowId: string) => {
  const hash = getFlowIdHash(flowId);
  return 40 + (hash % 460);
};

const getMockConversionRate = (flowId: string) => {
  const hash = getFlowIdHash(`${flowId}-conversion`);
  return 12 + (hash % 74);
};

const FlowNodeIcon = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
    <path d="M6 6H16M6 16H16M6 6V16M16 6V16" stroke="#0F766E" strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="6" cy="6" r="2.2" fill="#10B981" />
    <circle cx="16" cy="6" r="2.2" fill="#34D399" />
    <circle cx="6" cy="16" r="2.2" fill="#34D399" />
    <circle cx="16" cy="16" r="2.2" fill="#10B981" />
  </svg>
);


const EMPTY_FORM: FlowPayload = {
  name: '',
  description: '',
  trigger_type: 'default',
  trigger_value: '',
};

export default function FlowsPage() {
  const router = useRouter();
  const [flows, setFlows] = useState<FlowListItem[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive' | 'draft' | 'published'>('all');
  const [sortBy, setSortBy] = useState<'recent' | 'name' | 'active_first'>('recent');
  const [loading, setLoading] = useState(true);
  const [isOpen, setIsOpen] = useState(false);
  const [editingFlow, setEditingFlow] = useState<FlowItem | null>(null);
  const [form, setForm] = useState<FlowPayload>(EMPTY_FORM);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  const showToast = (message: string) => {
    setToastMessage(message);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const parseHttpStatus = (error: unknown): number | null => {
    if (!(error instanceof Error)) return null;
    const match = error.message.match(/HTTP\s+(\d{3})/i);
    return match ? Number(match[1]) : null;
  };

  const logFlowOperationError = ({ method, endpoint, error }: { method: string; endpoint: string; error: unknown }) => {
    console.error('[FlowsPage]', { method, endpoint, message: error instanceof Error ? error.message : String(error) });
  };

  const title = useMemo(() => (editingFlow ? 'Editar fluxo' : 'Novo fluxo'), [editingFlow]);

  const loadFlows = async () => {
    setLoading(true);
    try { setFlows(await listFlows()); } finally { setLoading(false); }
  };

  useEffect(() => { loadFlows(); }, []);

  const openCreate = () => { setEditingFlow(null); setForm(EMPTY_FORM); setIsOpen(true); };
  const openBuilder = () => {
    router.push('/dashboard/flow-builder');
  };
  const openEdit = (flow: FlowItem) => {
    setEditingFlow(flow);
    setForm({ name: flow.name, description: flow.description || '', trigger_type: flow.trigger_type === 'keyword' ? 'keyword' : 'default', trigger_value: flow.trigger_value || '' });
    setIsOpen(true);
  };

  const onSave = async () => {
    if (!form.name.trim()) return;
    try {
      if (editingFlow) { await updateFlow(editingFlow.id, form); }
      else { await createFlow({ ...form, name: form.name.trim(), nodes: [], edges: [] } as FlowPayload & { nodes: unknown[]; edges: unknown[] }); }
    } catch (error) {
      const status = parseHttpStatus(error);
      logFlowOperationError({ method: editingFlow ? 'PUT' : 'POST', endpoint: editingFlow ? `/api/flows/${editingFlow.id}` : '/api/flows', error });
      showToast(`Não foi possível salvar o flow${status ? ` (HTTP ${status})` : ''}.`);
      return;
    }
    setIsOpen(false);
    await loadFlows();
  };

  const onDelete = async (flowId: string) => {
    try {
      const response = await deleteFlow(flowId);
      showToast(response.success && response.mode === 'soft_delete' ? 'Flow em uso, removido da visualização' : 'Flow deletado com sucesso');
      await loadFlows();
    } catch (error) {
      showToast(`Não foi possível deletar${parseHttpStatus(error) ? ` (HTTP ${parseHttpStatus(error)})` : ''}.`);
    }
  };

  const onDuplicate = async (flowId: string) => {
    try { await duplicateFlow(flowId); showToast('Flow duplicado!'); await loadFlows(); }
    catch { showToast('Erro ao duplicar flow.'); }
  };

  const updateLocalState = (flowId: string, newStatus: 'active' | 'inactive') => {
    const isActive = newStatus === 'active';
    setFlows((prev) => prev.map((flow) => (flow.id === flowId ? { ...flow, is_active: isActive, status: newStatus } : flow)));
  };

  const toggleFlowStatus = async (flowId: string) => {
    const currentFlow = flows.find((flow) => flow.id === flowId);
    if (!currentFlow) return;

    const newStatus: 'active' | 'inactive' = currentFlow.status === 'active' || currentFlow.is_active ? 'inactive' : 'active';
    const previousStatus: 'active' | 'inactive' = currentFlow.status === 'active' || currentFlow.is_active ? 'active' : 'inactive';
    updateLocalState(flowId, newStatus);
    try {
      await updateFlowStatus(flowId, newStatus === 'active');
    } catch {
      updateLocalState(flowId, previousStatus);
      showToast('Erro ao atualizar status do fluxo');
    }
  };

  const published = flows.filter((f) => f.status === 'published' || f.status === 'active').length;
  const drafts = flows.filter((f) => f.status === 'draft' || f.status === 'inactive').length;
  const filteredFlows = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();
    const filtered = flows.filter((flow) => {
      if (normalizedSearch) {
        const searchableFields = [flow.name, flow.trigger_type, flow.trigger_value ?? '']
          .join(' ')
          .toLowerCase();
        if (!searchableFields.includes(normalizedSearch)) return false;
      }

      if (statusFilter === 'active' && !flow.is_active) return false;
      if (statusFilter === 'inactive' && flow.is_active) return false;
      if (statusFilter === 'draft' && flow.status !== 'draft') return false;
      if (statusFilter === 'published' && flow.status !== 'published') return false;

      return true;
    });

    return filtered.sort((a, b) => {
      if (sortBy === 'name') return a.name.localeCompare(b.name);

      if (sortBy === 'active_first') {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        return a.name.localeCompare(b.name);
      }

      const aDate = a.updated_at ? new Date(a.updated_at).getTime() : Number.NaN;
      const bDate = b.updated_at ? new Date(b.updated_at).getTime() : Number.NaN;
      const bothHaveValidDate = !Number.isNaN(aDate) && !Number.isNaN(bDate);

      if (bothHaveValidDate && aDate !== bDate) return bDate - aDate;
      if (!Number.isNaN(aDate) && Number.isNaN(bDate)) return -1;
      if (Number.isNaN(aDate) && !Number.isNaN(bDate)) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [flows, searchTerm, sortBy, statusFilter]);

  const flowsWithMetrics = useMemo(
    () =>
      filteredFlows.map((flow) => {
        const realExecutions = getFlowExecutions(flow);
        const realConversionRate = getFlowConversion(flow);

        return {
          ...flow,
          executions: realExecutions ?? getMockExecutions(flow.id),
          conversion_rate: realConversionRate ?? getMockConversionRate(flow.id),
        };
      }),
    [filteredFlows],
  );

  return (
    <main className="flex-1 bg-slate-50 py-6">
      <div className="mx-auto max-w-7xl space-y-6 px-6 font-sans">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="m-0 text-[22px] font-semibold tracking-[-0.02em] text-slate-900">Automações</h1>
          <p className="mt-1 text-sm text-slate-500">Gerencie fluxos de conversação e gatilhos</p>
        </div>
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-[18px] py-[9px] text-sm font-semibold tracking-[-0.01em] text-white transition hover:bg-emerald-700"
        >
          <span className="text-base leading-none">+</span> Novo fluxo
        </button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 border-b border-gray-200 pb-4 [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))]">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-green-100">
                <img src="/icons/total de fluxos.svg" alt="Total de fluxos" className="h-5 w-5 opacity-80" />
              </div>
              <div>
                <span className="text-xs uppercase tracking-wide text-gray-500">TOTAL DE FLUXOS</span>
                <span className="mt-1 block text-2xl font-semibold text-gray-900">{flows.length}</span>
                <span className="mt-1 block text-sm text-gray-400">Todos os fluxos criados</span>
              </div>
            </div>
            <svg className="self-start opacity-80" width="120" height="44" viewBox="0 0 120 44" fill="none" aria-hidden="true">
              <path d="M2 34 C14 29, 22 15, 34 17 C48 19, 57 31, 72 26 C86 21, 98 7, 118 9" stroke="#16A34A" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100">
                <img src="/icons/publicados.svg" alt="Publicados" className="h-5 w-5 opacity-80" />
              </div>
              <div>
                <span className="text-xs uppercase tracking-wide text-gray-500">PUBLICADOS</span>
                <span className="mt-1 block text-2xl font-semibold text-gray-900">{published}</span>
                <span className="mt-1 block text-sm text-gray-400">Fluxos ativos em produção</span>
              </div>
            </div>
            <svg className="self-start opacity-80" width="120" height="44" viewBox="0 0 120 44" fill="none" aria-hidden="true">
              <path d="M2 34 C14 28, 24 13, 38 15 C53 17, 61 31, 76 26 C90 21, 102 10, 118 8" stroke="#10B981" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-100">
                <img src="/icons/rascunho.svg" alt="Rascunhos" className="h-5 w-5 opacity-80" />
              </div>
              <div>
                <span className="text-xs uppercase tracking-wide text-gray-500">RASCUNHOS</span>
                <span className="mt-1 block text-2xl font-semibold text-gray-900">{drafts}</span>
                <span className="mt-1 block text-sm text-gray-400">Aguardando publicação</span>
              </div>
            </div>
            <svg className="self-start opacity-80" width="120" height="44" viewBox="0 0 120 44" fill="none" aria-hidden="true">
              <path d="M2 33 C16 27, 27 18, 40 20 C54 22, 62 31, 76 26 C90 21, 102 16, 118 10" stroke="#F59E0B" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-4">
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Buscar fluxos..."
            className="flex-1 rounded-xl border border-gray-100 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'inactive' | 'draft' | 'published')}
            className="w-52 rounded-xl border border-gray-100 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none"
          >
            <option value="all">Todos os status</option>
            <option value="active">Ativo</option>
            <option value="inactive">Inativo</option>
            <option value="draft">Rascunho</option>
            <option value="published">Publicado</option>
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'recent' | 'name' | 'active_first')}
            className="w-56 rounded-xl border border-gray-100 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none"
          >
            <option value="recent">Ordenar: Mais recentes</option>
            <option value="name">Ordenar: Nome</option>
            <option value="active_first">Ordenar: Ativos primeiro</option>
          </select>
        </div>
      </div>

      {/* Flow list */}
      <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4">
          <span className="text-xs font-semibold uppercase tracking-[0.05em] text-slate-500">Seus fluxos</span>
        </div>

        {loading ? (
          <div className="px-5 py-12 text-center text-sm text-slate-400">Carregando...</div>
        ) : filteredFlows.length === 0 ? (
          <div className="px-5 py-14 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-[22px]">⚡</div>
            <p className="mb-1.5 text-base font-semibold text-slate-900">Nenhum fluxo criado ainda</p>
            <p className="mb-5 text-sm text-slate-500">Crie seu primeiro fluxo de automação</p>
            <button
              onClick={openCreate}
              className="rounded-xl bg-emerald-600 px-5 py-[9px] text-sm font-semibold text-white transition hover:bg-emerald-700"
            >
              + Criar primeiro fluxo
            </button>
          </div>
        ) : (
          <div className="space-y-3 p-4 sm:space-y-4 sm:p-5">
            {flowsWithMetrics.map((flow) => {
              return (
                <div
                  key={flow.id}
                  className="flex flex-col gap-4 rounded-2xl bg-white transition hover:shadow-md lg:flex-row lg:items-center lg:justify-between"
                  style={{ display: 'flex', alignItems: 'center', gap: '1rem', padding: '1.5rem', border: '0.5px solid #E5E7EB' }}
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFlowStatus(flow.id);
                    }}
                    aria-label={flow.is_active ? 'Desativar fluxo' : 'Ativar fluxo'}
                    className="relative h-6 w-11 rounded-full border-0 p-0 transition-colors"
                    style={{ backgroundColor: flow.is_active ? '#10b981' : '#d1d5db' }}
                  >
                    <span
                      className="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform"
                      style={{ left: flow.is_active ? 22 : 2 }}
                    />
                  </button>

                  <div className="flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: '#E8F5F3' }}>
                    <FlowNodeIcon />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-slate-900 sm:text-base">{flow.name}</span>
                      <span
                        className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold"
                        style={{
                          background: flow.is_active ? '#D1FAE5' : '#F3F4F6',
                          color: flow.is_active ? '#065F46' : '#6B7280',
                        }}
                      >
                        {flow.is_active ? 'Ativo' : 'Inativo'}
                      </span>
                    </div>
                    <span className="mt-1 block text-xs text-slate-500">
                      Trigger: {flow.trigger_type || 'default'}
                      {flow.trigger_value ? ` · ${flow.trigger_value}` : ''} · {getUpdatedLabel(flow.updated_at)}
                    </span>
                  </div>

                  <div className="flex items-center gap-4">
                    <div className="inline-flex items-center gap-2">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M3 12L21 4L15 21L11 13L3 12Z" stroke="#64748B" strokeWidth="1.7" strokeLinejoin="round" />
                      </svg>
                      <div>
                        <div className="text-[16px] font-semibold leading-none text-slate-900">{flow.executions}</div>
                        <div className="text-[10px] uppercase tracking-[0.04em] text-slate-500">Execuções</div>
                      </div>
                    </div>
                    <div className="inline-flex items-center gap-2">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M12 4L20 19H4L12 4Z" stroke="#64748B" strokeWidth="1.7" strokeLinejoin="round" />
                      </svg>
                      <div>
                        <div className="text-[16px] font-semibold leading-none text-slate-900">{Math.round(flow.conversion_rate ?? 0)}%</div>
                        <div className="text-[10px] uppercase tracking-[0.04em] text-slate-500">Conversão</div>
                      </div>
                    </div>
                  </div>

                  <div className="relative flex w-full flex-wrap items-center gap-2 sm:justify-end lg:w-auto">
                    <button onClick={(e) => { e.stopPropagation(); openEdit(flow); }} className="whitespace-nowrap rounded-xl border border-gray-100 bg-transparent px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:shadow-sm">Editar</button>
                    <Link href={`/dashboard/flows/${flow.id}/analytics`} onClick={(e) => e.stopPropagation()} className="whitespace-nowrap rounded-xl border border-gray-100 bg-transparent px-3 py-1.5 text-xs font-semibold text-slate-600 no-underline transition hover:shadow-sm">Analytics</Link>
                    <Link href={`/dashboard/flow-builder?flow_id=${flow.id}`} onClick={(e) => e.stopPropagation()} className="whitespace-nowrap rounded-xl bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white no-underline transition hover:bg-emerald-700">Abrir builder</Link>
                    <div className="relative">
                      <button onClick={(e) => { e.stopPropagation(); setOpenDropdown(openDropdown === flow.id ? null : flow.id); }} className="rounded-xl border border-gray-100 bg-transparent px-2.5 py-1.5 text-sm leading-none text-slate-600 transition hover:shadow-sm">⋯</button>
                      {openDropdown === flow.id && (
                        <div className="absolute right-0 top-[calc(100%+4px)] z-10 min-w-[140px] overflow-hidden rounded-xl border border-gray-100 bg-white shadow-md">
                          <button onClick={(e) => { e.stopPropagation(); onDuplicate(flow.id); setOpenDropdown(null); }} className="w-full bg-transparent px-3.5 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50">Duplicar</button>
                          <button onClick={(e) => { e.stopPropagation(); onDelete(flow.id); setOpenDropdown(null); }} className="w-full bg-transparent px-3.5 py-2 text-left text-sm text-red-600 transition hover:bg-red-50">Deletar</button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div
        className="rounded-2xl p-5 shadow-sm"
        style={{ background: 'linear-gradient(135deg, #E8F5F3 0%, #D1FAE5 100%)', border: '0.5px solid #A7F3D0' }}
      >
        <div className="flex flex-col items-start gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white">
              <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
                <rect x="5" y="8" width="26" height="20" rx="5" fill="#ECFDF5" stroke="#6EE7B7" />
                <circle cx="11" cy="14" r="2.5" fill="#10B981" />
                <circle cx="25" cy="14" r="2.5" fill="#34D399" />
                <circle cx="18" cy="22" r="2.5" fill="#059669" />
                <path d="M13.5 14H22.5" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M12.8 15.8L16.2 20.2" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M23.2 15.8L19.8 20.2" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>

            <div>
              <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700">Dica rápida</span>
              <h3 className="mt-1 text-[16px] font-semibold leading-[1.3] text-slate-900">
                Construa fluxos mais inteligentes com o builder visual
              </h3>
              <p className="mt-1 text-[13px] text-slate-600">
                Arraste blocos, conecte gatilhos e publique automações em minutos com uma experiência visual guiada.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={openBuilder}
            className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-95"
            style={{ background: '#10b981' }}
          >
            Abrir builder <span aria-hidden="true">↗</span>
          </button>
        </div>
      </div>

      {/* Toast */}
      {toastMessage && (
        <div style={{ position: 'fixed', right: 24, bottom: 24, background: '#111', color: '#fff', padding: '10px 16px', borderRadius: 10, fontSize: 13, boxShadow: '0 8px 24px rgba(0,0,0,0.2)', zIndex: 50 }}>
          {toastMessage}
        </div>
      )}

      {/* Modal */}
      {isOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, backdropFilter: 'blur(4px)' }}>
          <div style={{ background: '#fff', padding: 28, width: 440, borderRadius: 16, boxShadow: '0 24px 64px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column', gap: 16 }}>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600, color: '#111' }}>{title}</h2>
            {(['name', 'description'] as const).map((field) => (
              <div key={field} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: '#555', textTransform: 'capitalize' }}>{field === 'name' ? 'Nome' : 'Descrição'}</label>
                <input value={form[field] || ''} onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))} style={{ border: '1px solid #e8e6e0', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit' }} />
              </div>
            ))}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#555' }}>Trigger type</label>
              <select value={form.trigger_type} onChange={(e) => setForm((prev) => ({ ...prev, trigger_type: e.target.value as 'keyword' | 'default' }))} style={{ border: '1px solid #e8e6e0', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit', background: '#fff' }}>
                <option value="default">default</option>
                <option value="keyword">keyword</option>
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#555' }}>Trigger value</label>
              <input value={form.trigger_value || ''} onChange={(e) => setForm((prev) => ({ ...prev, trigger_value: e.target.value }))} style={{ border: '1px solid #e8e6e0', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
              <button onClick={() => setIsOpen(false)} style={{ background: 'transparent', border: '1px solid #e8e6e0', padding: '8px 16px', borderRadius: 8, fontSize: 13, cursor: 'pointer', color: '#555', fontWeight: 500 }}>Cancelar</button>
              <button onClick={onSave} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '8px 20px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Salvar</button>
            </div>
          </div>
        </div>
      )}
      </div>
    </main>
  );
}
