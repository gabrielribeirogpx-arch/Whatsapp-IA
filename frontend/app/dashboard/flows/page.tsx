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

  const published = flows.filter((f) => f.status === 'published').length;
  const drafts = flows.filter((f) => f.status === 'draft').length;
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
      <div className="max-w-7xl mx-auto px-6 space-y-6" style={{ fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: '#111', letterSpacing: '-0.02em' }}>Automações</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#888' }}>Gerencie fluxos de conversação e gatilhos</p>
        </div>
        <button onClick={openCreate} style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#16a34a', color: '#fff', border: 'none', padding: '9px 18px', borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: 'pointer', letterSpacing: '-0.01em' }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> Novo fluxo
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {[
          {
            label: 'TOTAL DE FLUXOS',
            value: flows.length,
            helperText: 'Todos os fluxos criados',
            colorClass: 'text-emerald-600',
            iconBgClass: 'bg-emerald-100',
            icon: '📊',
            sparkline: 'M2 20 C8 18, 12 9, 18 11 C23 13, 27 7, 34 9 C40 10, 45 5, 50 7',
          },
          {
            label: 'PUBLICADOS',
            value: published,
            helperText: 'Fluxos ativos em produção',
            colorClass: 'text-amber-600',
            iconBgClass: 'bg-amber-100',
            icon: '✅',
            sparkline: 'M2 20 C10 17, 14 12, 20 14 C25 15, 30 9, 36 10 C42 11, 47 6, 50 8',
          },
          {
            label: 'RASCUNHOS',
            value: drafts,
            helperText: 'Aguardando publicação',
            colorClass: 'text-slate-500',
            iconBgClass: 'bg-slate-100',
            icon: '📝',
            sparkline: 'M2 21 C8 19, 12 13, 18 14 C24 15, 28 10, 34 12 C40 13, 45 9, 50 11',
          },
        ].map((stat) => (
          <div key={stat.label} className="rounded-2xl shadow-sm border border-gray-100 bg-white p-5 transition hover:shadow-md">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className={`flex h-9 w-9 items-center justify-center rounded-xl text-sm ${stat.iconBgClass} ${stat.colorClass}`}>
                  {stat.icon}
                </div>
                <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">{stat.label}</span>
              </div>
              <svg width="52" height="24" viewBox="0 0 52 24" fill="none" aria-hidden="true">
                <path
                  d={stat.sparkline}
                  className={stat.colorClass}
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="mt-3">
              <span className="block text-2xl font-semibold text-slate-900">{stat.value}</span>
              <span className="mt-1.5 inline-block text-xs text-slate-500">{stat.helperText}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Buscar fluxos..."
          style={{ border: '1px solid #e8e6e0', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit', background: '#fff' }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'inactive' | 'draft' | 'published')}
          style={{ border: '1px solid #e8e6e0', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit', background: '#fff' }}
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
          style={{ border: '1px solid #e8e6e0', borderRadius: 10, padding: '10px 12px', fontSize: 13, color: '#111', outline: 'none', fontFamily: 'inherit', background: '#fff' }}
        >
          <option value="recent">Ordenar: Mais recentes</option>
          <option value="name">Ordenar: Nome</option>
          <option value="active_first">Ordenar: Ativos primeiro</option>
        </select>
        </div>
      </div>

      {/* Flow list */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #f0f0ee' }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Seus fluxos</span>
        </div>

        {loading ? (
          <div style={{ padding: '48px 20px', textAlign: 'center', color: '#aaa', fontSize: 13 }}>Carregando...</div>
        ) : filteredFlows.length === 0 ? (
          <div style={{ padding: '56px 20px', textAlign: 'center' }}>
            <div style={{ width: 48, height: 48, background: '#f0fdf4', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', fontSize: 22 }}>⚡</div>
            <p style={{ margin: '0 0 6px', fontSize: 15, fontWeight: 600, color: '#111' }}>Nenhum fluxo criado ainda</p>
            <p style={{ margin: '0 0 20px', fontSize: 13, color: '#888' }}>Crie seu primeiro fluxo de automação</p>
            <button onClick={openCreate} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '9px 20px', borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>+ Criar primeiro fluxo</button>
          </div>
        ) : (
          <div>
            {filteredFlows.map((flow, index) => {
              return (
                <div key={flow.id} className="flex flex-col gap-3 px-5 py-4 transition sm:gap-4 lg:flex-row lg:items-center lg:justify-between" style={{ borderBottom: index < filteredFlows.length - 1 ? '1px solid #f0f0ee' : 'none', transition: 'background 0.15s' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#fafaf9'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
                      <Switch
                        checked={flow.is_active}
                        onChange={(value) => handleToggle(flow.id, value)}
                        tooltip={flow.is_active ? 'Desativar fluxo' : 'Ativar fluxo'}
                      />
                      <div style={{ width: 28, height: 28, borderRadius: 8, background: '#f1f5f9', border: '1px solid #e2e8f0', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13 }}>
                        ⚡
                      </div>
                      <span style={{ fontSize: 14, fontWeight: 600, color: '#111' }}>{flow.name}</span>
                      {flow.is_active ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          Ativo
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500 ring-1 ring-slate-200">
                          <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                          OFF
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 12, color: '#64748b', display: 'block' }}>
                      Trigger: {flow.trigger_type || 'default'}{flow.trigger_value ? ` · ${flow.trigger_value}` : ''}
                    </span>
                    <span style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginTop: 2 }}>
                      {getUpdatedLabel(flow.updated_at)}
                    </span>
                  </div>

                  <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
                    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: '6px 10px', background: '#f8fafc', minWidth: 92 }}>
                      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>Execuções</div>
                      <div style={{ fontSize: 14, color: '#0f172a', fontWeight: 700 }}>{getFlowExecutions(flow)}</div>
                    </div>
                    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: '6px 10px', background: '#f8fafc', minWidth: 92 }}>
                      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>Conversão</div>
                      <div style={{ fontSize: 14, color: '#0f172a', fontWeight: 700 }}>{getFlowConversion(flow)}</div>
                    </div>
                  </div>

                  <div className="relative flex w-full flex-wrap items-center gap-2 lg:w-auto lg:justify-end">
                    <button onClick={(e) => { e.stopPropagation(); openEdit(flow); }} style={{ background: 'transparent', border: '1px solid #e8e6e0', padding: '6px 12px', borderRadius: 8, fontSize: 12, cursor: 'pointer', color: '#555', fontWeight: 500, whiteSpace: 'nowrap' }}>Editar</button>
                    <Link href={`/dashboard/flows/${flow.id}/analytics`} onClick={(e) => e.stopPropagation()} style={{ background: 'transparent', border: '1px solid #e8e6e0', padding: '6px 12px', borderRadius: 8, fontSize: 12, color: '#555', textDecoration: 'none', fontWeight: 500, whiteSpace: 'nowrap' }}>Analytics</Link>
                    <Link href={`/dashboard/flow-builder?flow_id=${flow.id}`} onClick={(e) => e.stopPropagation()} style={{ background: '#16a34a', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap' }}>Abrir builder</Link>
                    <div style={{ position: 'relative' }}>
                      <button onClick={(e) => { e.stopPropagation(); setOpenDropdown(openDropdown === flow.id ? null : flow.id); }} style={{ background: 'transparent', border: '1px solid #e8e6e0', padding: '6px 10px', borderRadius: 8, fontSize: 14, cursor: 'pointer', color: '#555', lineHeight: 1 }}>⋯</button>
                      {openDropdown === flow.id && (
                        <div style={{ position: 'absolute', right: 0, top: 'calc(100% + 4px)', background: '#fff', border: '1px solid #e8e6e0', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.1)', minWidth: 140, zIndex: 10, overflow: 'hidden' }}>
                          <button onClick={(e) => { e.stopPropagation(); onDuplicate(flow.id); setOpenDropdown(null); }} style={{ width: '100%', textAlign: 'left', padding: '9px 14px', border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 13, color: '#333' }}>Duplicar</button>
                          <button onClick={(e) => { e.stopPropagation(); onDelete(flow.id); setOpenDropdown(null); }} style={{ width: '100%', textAlign: 'left', padding: '9px 14px', border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 13, color: '#dc2626' }}>Deletar</button>
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

function Switch({ checked, onChange, tooltip }: { checked: boolean; onChange: (value: boolean) => void; tooltip: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      title={tooltip}
      aria-label={tooltip}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      style={{
        width: 36,
        height: 20,
        borderRadius: 999,
        border: 'none',
        cursor: 'pointer',
        background: checked ? '#16a34a' : '#9ca3af',
        padding: 2,
        display: 'inline-flex',
        alignItems: 'center',
        transition: 'background 0.15s ease',
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          background: '#fff',
          transform: checked ? 'translateX(16px)' : 'translateX(0)',
          transition: 'transform 0.15s ease',
        }}
      />
    </button>
  );
}
