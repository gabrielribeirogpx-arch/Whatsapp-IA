'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

import { createFlow, deleteFlow, duplicateFlow, listFlows, updateFlow, updateFlowStatus } from '@/lib/api';
import { FlowItem, FlowPayload } from '@/lib/types';

type FlowListItem = FlowItem & {
  status?: string;
  is_published?: boolean;
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
  return typeof value === 'number' ? value : 0;
};

const getFlowConversion = (flow: FlowListItem) => {
  const metrics = flow as unknown as Record<string, unknown>;
  const candidates = [metrics.conversion_rate, metrics.conversion, metrics.conversionPercent, metrics.completed_rate];
  const value = candidates.find((candidate) => typeof candidate === 'number' && Number.isFinite(candidate));
  if (typeof value !== 'number') return '0%';
  return `${Math.round(value)}%`;
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

  const updateLocalState = (flowId: string, isActive: boolean) => {
    setFlows((prev) => prev.map((flow) => (flow.id === flowId ? { ...flow, is_active: isActive } : flow)));
  };

  const handleToggle = async (flowId: string, isActive: boolean) => {
    updateLocalState(flowId, isActive);
    try {
      await updateFlowStatus(flowId, isActive);
    } catch {
      updateLocalState(flowId, !isActive);
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
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 16,
          borderBottom: '1px solid #E5E7EB',
          paddingBottom: 16,
        }}
      >
        <div className="relative rounded-2xl border border-gray-100 p-5 shadow-sm transition hover:shadow-md" style={{ background: '#E8F5F3' }}>
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl text-sm">🔄</div>
            <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">TOTAL DE FLUXOS</span>
          </div>
          <div className="mt-3">
            <span className="block text-[32px] font-semibold leading-none text-slate-900">{flows.length}</span>
            <span className="mt-1.5 inline-block text-[12px] text-slate-500">Todos os fluxos criados</span>
          </div>
          <svg className="absolute bottom-4 right-4" width="52" height="24" viewBox="0 0 52 24" fill="none" aria-hidden="true">
            <path d="M2 20 C8 18, 12 9, 18 11 C23 13, 27 7, 34 9 C40 10, 45 5, 50 7" stroke="#0F766E" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <div className="relative rounded-2xl border border-gray-100 p-5 shadow-sm transition hover:shadow-md" style={{ background: '#E8F5F3' }}>
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl text-sm">✈️</div>
            <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">PUBLICADOS</span>
          </div>
          <div className="mt-3">
            <span className="block text-[32px] font-semibold leading-none text-slate-900">{published}</span>
            <span className="mt-1.5 inline-block text-[12px] text-slate-500">Fluxos ativos em produção</span>
          </div>
          <svg className="absolute bottom-4 right-4" width="52" height="24" viewBox="0 0 52 24" fill="none" aria-hidden="true">
            <path d="M2 20 C10 17, 14 12, 20 14 C25 15, 30 9, 36 10 C42 11, 47 6, 50 8" stroke="#0F766E" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <div className="relative rounded-2xl border border-gray-100 p-5 shadow-sm transition hover:shadow-md" style={{ background: '#FEF3C7' }}>
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl text-sm">📦</div>
            <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">RASCUNHOS</span>
          </div>
          <div className="mt-3">
            <span className="block text-[32px] font-semibold leading-none text-slate-900">{drafts}</span>
            <span className="mt-1.5 inline-block text-[12px] text-slate-500">Aguardando publicação</span>
          </div>
          <svg className="absolute bottom-4 right-4" width="52" height="24" viewBox="0 0 52 24" fill="none" aria-hidden="true">
            <path d="M2 21 C8 19, 12 13, 18 14 C24 15, 28 10, 34 12 C40 13, 45 9, 50 11" stroke="#92400E" strokeWidth="2" strokeLinecap="round" />
          </svg>
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
            {filteredFlows.map((flow) => {
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
                      handleToggle(flow.id, !flow.is_active);
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
                        <div className="text-[16px] font-semibold leading-none text-slate-900">{getFlowExecutions(flow)}</div>
                        <div className="text-[10px] uppercase tracking-[0.04em] text-slate-500">Execuções</div>
                      </div>
                    </div>
                    <div className="inline-flex items-center gap-2">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M12 4L20 19H4L12 4Z" stroke="#64748B" strokeWidth="1.7" strokeLinejoin="round" />
                      </svg>
                      <div>
                        <div className="text-[16px] font-semibold leading-none text-slate-900">{getFlowConversion(flow)}</div>
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
        className="rounded-2xl border border-emerald-100 p-5 shadow-sm"
        style={{ background: 'linear-gradient(120deg, #ffffff 0%, #f0fdf4 55%, #dcfce7 100%)' }}
      >
        <div className="grid grid-cols-1 items-center gap-4 md:grid-cols-[120px_minmax(0,1fr)_auto]">
          <div
            style={{
              width: '100%',
              maxWidth: 110,
              minHeight: 88,
              borderRadius: 14,
              background: 'rgba(22, 163, 74, 0.08)',
              border: '1px solid rgba(22, 163, 74, 0.14)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg width="74" height="62" viewBox="0 0 74 62" fill="none" aria-hidden="true">
              <rect x="5" y="9" width="64" height="44" rx="10" fill="#ECFDF5" stroke="#A7F3D0" />
              <circle cx="20" cy="24" r="4" fill="#34D399" />
              <rect x="29" y="21" width="28" height="6" rx="3" fill="#86EFAC" />
              <rect x="15" y="33" width="44" height="5" rx="2.5" fill="#BBF7D0" />
              <path d="M17 44C23 36 32 34 38 38C44 42 50 42 57 35" stroke="#16A34A" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </div>

          <div>
            <span className="inline-flex rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-emerald-700">
              Dica rápida
            </span>
            <h3 style={{ margin: '10px 0 6px', fontSize: 20, fontWeight: 700, color: '#0f172a', lineHeight: 1.2 }}>
              Construa fluxos mais inteligentes com o builder visual
            </h3>
            <p style={{ margin: 0, color: '#475569', fontSize: 14, maxWidth: 640 }}>
              Arraste blocos, conecte gatilhos e publique automações em minutos com uma experiência visual guiada.
            </p>
          </div>

          <Link
            href="/dashboard/flow-builder"
            className="inline-flex w-full items-center justify-center rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white no-underline transition hover:bg-emerald-700 md:w-auto"
          >
            Abrir builder
          </Link>
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
