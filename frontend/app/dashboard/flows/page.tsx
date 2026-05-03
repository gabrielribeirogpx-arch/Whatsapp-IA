'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

import { createFlow, deleteFlow, duplicateFlow, listFlows, updateFlow } from '@/lib/api';
import { FlowItem, FlowPayload } from '@/lib/types';

const EMPTY_FORM: FlowPayload = {
  name: '',
  description: '',
  trigger_type: 'default',
  trigger_value: '',
};

export default function FlowsPage() {
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isOpen, setIsOpen] = useState(false);
  const [editingFlow, setEditingFlow] = useState<FlowItem | null>(null);
  const [form, setForm] = useState<FlowPayload>(EMPTY_FORM);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  const [isMobile, setIsMobile] = useState(false);

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
    const tenantPresent = typeof window !== 'undefined' && !!localStorage.getItem('tenant_id');
    console.error('[FlowsPage] Falha em operação de flow', {
      method,
      endpoint,
      tenantPresent,
      status: parseHttpStatus(error),
      message: error instanceof Error ? error.message : String(error),
    });
  };

  const title = useMemo(() => (editingFlow ? 'Editar fluxo' : 'Novo fluxo'), [editingFlow]);

  const loadFlows = async () => {
    setLoading(true);
    try {
      setFlows(await listFlows());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadFlows();
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia('(max-width: 768px)');
    const applyMatch = (matches: boolean) => setIsMobile(matches);

    applyMatch(mediaQuery.matches);

    const handleChange = (event: MediaQueryListEvent) => applyMatch(event.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  const openCreate = () => {
    setEditingFlow(null);
    setForm(EMPTY_FORM);
    setIsOpen(true);
  };

  const openEdit = (flow: FlowItem) => {
    setEditingFlow(flow);
    setForm({
      name: flow.name,
      description: flow.description || '',
      trigger_type: flow.trigger_type === 'keyword' ? 'keyword' : 'default',
      trigger_value: flow.trigger_value || '',
    });
    setIsOpen(true);
  };

  const onSave = async () => {
    if (!form.name.trim()) return;
    try {
      if (editingFlow) {
        await updateFlow(editingFlow.id, form);
      } else {
        const createPayload = {
          ...form,
          name: form.name.trim(),
          nodes: [],
          edges: [],
        };
        await createFlow(createPayload as FlowPayload & { nodes: unknown[]; edges: unknown[] });
      }
    } catch (error) {
      const status = parseHttpStatus(error);
      const endpoint = editingFlow ? `/api/flows/${editingFlow.id}` : '/api/flows';
      logFlowOperationError({
        method: editingFlow ? 'PUT' : 'POST',
        endpoint,
        error,
      });
      showToast(`Não foi possível salvar o flow${status ? ` (HTTP ${status})` : ''}.`);
      return;
    }

    setIsOpen(false);
    await loadFlows();
  };

  const onDelete = async (flowId: string) => {
    try {
      const response = await deleteFlow(flowId);
      if (response.success === true && response.mode === 'soft_delete') {
        showToast('Flow em uso, removido apenas da visualização');
      } else {
        showToast('Flow deletado com sucesso');
      }
      await loadFlows();
    } catch (error) {
      const status = parseHttpStatus(error);
      logFlowOperationError({ method: 'DELETE', endpoint: `/api/flows/${flowId}`, error });
      showToast(`Não foi possível deletar o flow${status ? ` (HTTP ${status})` : ''}.`);
    }
  };

  const onDuplicate = async (flowId: string) => {
    await duplicateFlow(flowId);
    await loadFlows();
    showToast('Flow duplicado com sucesso');
  };

  return (
    <div
      style={{
        maxWidth: 1120,
        margin: '0 auto',
        padding: 'clamp(16px, 3vw, 32px)',
      }}
    >
      <div style={{ border: '0.5px solid var(--color-border-tertiary)', borderRadius: 16, overflow: 'hidden', background: 'var(--color-background-primary)' }}>
        <div style={{ padding: '2rem', borderBottom: '0.5px solid var(--color-border-tertiary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: '24px', fontWeight: 500, margin: 0, color: 'var(--color-text-primary)' }}>Automações</h1>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', margin: '6px 0 0' }}>Gerencie fluxos de conversação e gatilhos</p>
          </div>
          <button onClick={openCreate} style={{ background: '#075E54', color: 'white', border: 'none', padding: '8px 16px', borderRadius: 'var(--border-radius-md)', fontSize: '13px', fontWeight: 500, cursor: 'pointer' }}>
            + Novo fluxo
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', padding: '2rem', borderBottom: '0.5px solid var(--color-border-tertiary)' }}>
          <div style={{ background: 'var(--color-background-secondary)', padding: '1rem', borderRadius: 'var(--border-radius-md)' }}>
            <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', margin: '0 0 10px', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Total de fluxos</p>
            <p style={{ fontSize: '32px', fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{flows.length}</p>
          </div>
          <div style={{ background: 'var(--color-background-secondary)', padding: '1rem', borderRadius: 'var(--border-radius-md)' }}>
            <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', margin: '0 0 10px', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Publicados</p>
            <p style={{ fontSize: '32px', fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{flows.filter((f) => (f as FlowItem & { status?: string }).status === 'published').length}</p>
          </div>
          <div style={{ background: 'var(--color-background-secondary)', padding: '1rem', borderRadius: 'var(--border-radius-md)' }}>
            <p style={{ fontSize: '11px', color: 'var(--color-text-secondary)', margin: '0 0 10px', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Rascunhos</p>
            <p style={{ fontSize: '32px', fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{flows.filter((f) => (f as FlowItem & { status?: string }).status === 'draft').length}</p>
          </div>
        </div>

        {loading ? (
          <p style={{ padding: '2rem' }}>Carregando...</p>
        ) : flows.length === 0 ? (
          <div style={{ padding: '4rem 2rem', textAlign: 'center', background: 'var(--color-background-secondary)', borderRadius: 'var(--border-radius-md)', margin: '2rem' }}>
            <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--color-text-primary)', margin: '0 0 8px' }}>Nenhum fluxo criado ainda</p>
            <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', margin: '0 0 1.5rem' }}>Crie seu primeiro fluxo de automação</p>
            <button onClick={openCreate} style={{ background: '#075E54', color: 'white', border: 'none', padding: '10px 20px', borderRadius: 'var(--border-radius-md)', fontSize: '13px', fontWeight: 500, cursor: 'pointer' }}>
              + Criar primeiro fluxo
            </button>
          </div>
        ) : (
          <div style={{ padding: '2rem' }}>
            <h2 style={{ fontSize: '14px', fontWeight: 500, margin: '0 0 1.5rem', color: 'var(--color-text-primary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Seus fluxos</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {flows.map((flow) => {
                const status = (flow as FlowItem & { status?: string }).status;
                return (
                  <div key={flow.id} style={{ background: 'var(--color-background-secondary)', padding: '1.5rem', borderRadius: 'var(--border-radius-md)', border: '0.5px solid var(--color-border-tertiary)', display: 'flex', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'flex-start' : 'center', justifyContent: 'space-between', gap: 12, transition: 'all 0.2s', cursor: 'pointer' }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-background-primary)'; e.currentTarget.style.borderColor = 'var(--color-border-secondary)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-background-secondary)'; e.currentTarget.style.borderColor = 'var(--color-border-tertiary)'; }}>
                    <div style={{ flex: 1, width: '100%' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px', flexWrap: 'wrap' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 500, margin: 0, color: 'var(--color-text-primary)' }}>{flow.name}</h3>
                        {status === 'published' && <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: 'var(--color-background-success)', color: 'var(--color-text-success)', padding: '3px 10px', borderRadius: 'var(--border-radius-md)', fontSize: '11px', fontWeight: 500 }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--color-text-success)' }}></span>Publicado</span>}
                        {status === 'draft' && <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: 'var(--color-background-warning)', color: 'var(--color-text-warning)', padding: '3px 10px', borderRadius: 'var(--border-radius-md)', fontSize: '11px', fontWeight: 500 }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--color-text-warning)' }}></span>Rascunho</span>}
                      </div>
                      <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--color-text-tertiary)', flexWrap: 'wrap' }}>
                        <span>Trigger: {flow.trigger_type || 'default'}</span>
                        {flow.trigger_value && <span>Valor: {flow.trigger_value}</span>}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', width: isMobile ? '100%' : 'auto', flexWrap: 'wrap', position: 'relative' }}>
                      <button onClick={(e) => { e.stopPropagation(); openEdit(flow); }} style={{ background: 'transparent', border: '0.5px solid var(--color-border-secondary)', padding: '6px 12px', borderRadius: 'var(--border-radius-md)', fontSize: '12px', cursor: 'pointer', color: 'var(--color-text-primary)', width: isMobile ? '100%' : 'auto' }}>Editar</button>
                      <Link href={`/dashboard/flows/${flow.id}/analytics`} onClick={(e) => e.stopPropagation()} style={{ background: 'transparent', border: '0.5px solid var(--color-border-secondary)', padding: '6px 12px', borderRadius: 'var(--border-radius-md)', fontSize: '12px', color: 'var(--color-text-primary)', textDecoration: 'none', width: isMobile ? '100%' : 'auto' }}>Analytics</Link>
                      <Link href={`/dashboard/flow-builder?flow_id=${flow.id}`} onClick={(e) => e.stopPropagation()} style={{ background: '#075E54', color: 'white', border: 'none', padding: '6px 12px', borderRadius: 'var(--border-radius-md)', fontSize: '12px', fontWeight: 500, textDecoration: 'none', width: isMobile ? '100%' : 'auto' }}>Abrir builder</Link>
                      <div style={{ position: 'relative', width: isMobile ? '100%' : 'auto' }}>
                        <button onClick={(e) => { e.stopPropagation(); setOpenDropdown(openDropdown === flow.id ? null : flow.id); }} style={{ background: 'transparent', border: '0.5px solid var(--color-border-secondary)', padding: '6px 8px', borderRadius: 'var(--border-radius-md)', fontSize: '16px', cursor: 'pointer', color: 'var(--color-text-primary)', width: isMobile ? '100%' : 'auto' }}>⋯</button>
                        {openDropdown === flow.id && (
                          <div style={{ position: 'absolute', right: 0, top: '100%', marginTop: '4px', background: 'var(--color-background-primary)', border: '0.5px solid var(--color-border-secondary)', borderRadius: 'var(--border-radius-md)', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', minWidth: '140px', zIndex: 10 }}>
                            <button onClick={(e) => { e.stopPropagation(); onDuplicate(flow.id); setOpenDropdown(null); }} style={{ width: '100%', textAlign: 'left', padding: '8px 12px', border: 'none', background: 'transparent', cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-primary)' }}>Duplicar</button>
                            <button onClick={(e) => { e.stopPropagation(); onDelete(flow.id); setOpenDropdown(null); }} style={{ width: '100%', textAlign: 'left', padding: '8px 12px', border: 'none', background: 'transparent', cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-danger)' }}>Deletar</button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {toastMessage && (
        <div
          style={{
            position: 'fixed',
            right: 24,
            bottom: 24,
            backgroundColor: '#111827',
            color: '#fff',
            padding: '10px 14px',
            borderRadius: 8,
            boxShadow: '0 8px 20px rgba(0,0,0,0.2)'
          }}
        >
          {toastMessage}
        </div>
      )}

      {isOpen && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: '#fff', padding: 20, width: 420, borderRadius: 8, display: 'grid', gap: 12 }}>
            <h2>{title}</h2>
            <label>
              Nome
              <input value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} style={{ width: '100%' }} />
            </label>
            <label>
              Descrição
              <input value={form.description || ''} onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))} style={{ width: '100%' }} />
            </label>
            <label>
              Trigger type
              <select value={form.trigger_type} onChange={(e) => setForm((prev) => ({ ...prev, trigger_type: e.target.value as 'keyword' | 'default' }))} style={{ width: '100%' }}>
                <option value="keyword">keyword</option>
                <option value="default">default</option>
              </select>
            </label>
            <label>
              Trigger value
              <input value={form.trigger_value || ''} onChange={(e) => setForm((prev) => ({ ...prev, trigger_value: e.target.value }))} style={{ width: '100%' }} />
            </label>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setIsOpen(false)}>Cancelar</button>
              <button onClick={onSave}>Salvar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
