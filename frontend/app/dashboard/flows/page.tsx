'use client';

import { CSSProperties, useEffect, useMemo, useState } from 'react';
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
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
          marginBottom: 24,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'grid', gap: 6 }}>
          <h1 style={{ margin: 0, fontSize: '2rem', fontWeight: 800, lineHeight: 1.1 }}>Flows</h1>
          <p style={{ margin: 0, color: '#6b7280' }}>Gerencie automações, gatilhos e versões dos seus fluxos.</p>
        </div>
        <button
          onClick={openCreate}
          style={{
            backgroundColor: '#16a34a',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '10px 16px',
            fontWeight: 700,
            cursor: 'pointer',
            marginLeft: 'auto',
          }}
        >
          + Novo fluxo
        </button>
      </div>

      {loading ? (
        <p>Carregando...</p>
      ) : flows.length === 0 ? (
        <div
          style={{
            width: '100%',
            backgroundColor: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: 16,
            boxShadow: '0 10px 30px rgba(15, 23, 42, 0.06)',
            padding: '28px 24px',
            display: 'grid',
            gap: 8,
          }}
        >
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#111827' }}>Você ainda não criou nenhum fluxo</h2>
          <p style={{ margin: 0, color: '#6b7280' }}>Crie seu primeiro fluxo para automatizar atendimentos no WhatsApp.</p>
          <button
            onClick={openCreate}
            style={{
              marginTop: 8,
              width: 'fit-content',
              backgroundColor: '#16a34a',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '10px 16px',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            + Criar fluxo
          </button>
        </div>
      ) : (
        <div
          style={{
            width: '100%',
            backgroundColor: '#ffffff',
            border: '1px solid #e5e7eb',
            borderRadius: 16,
            boxShadow: '0 10px 30px rgba(15, 23, 42, 0.06)',
            padding: 20,
            display: 'grid',
            gap: 12,
          }}
        >
          {!isMobile && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(160px, 1.3fr) minmax(120px, 1fr) minmax(150px, 1fr) minmax(90px, 0.8fr) minmax(280px, 1.6fr)',
                gap: 16,
                padding: '2px 12px 10px',
                color: '#6b7280',
                fontSize: 13,
                fontWeight: 700,
              }}
            >
              <span>Nome</span>
              <span>Trigger</span>
              <span>Valor</span>
              <span>Status</span>
              <span>Ações</span>
            </div>
          )}

          {flows.map((flow) => {
            const rowStyle: CSSProperties = isMobile
              ? {
                  display: 'grid',
                  gap: 12,
                  border: '1px solid #f3f4f6',
                  borderRadius: 12,
                  padding: 14,
                  transition: 'background-color 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                }
              : {
                  display: 'grid',
                  gridTemplateColumns: 'minmax(160px, 1.3fr) minmax(120px, 1fr) minmax(150px, 1fr) minmax(90px, 0.8fr) minmax(280px, 1.6fr)',
                  gap: 16,
                  alignItems: 'center',
                  border: '1px solid #f3f4f6',
                  borderRadius: 12,
                  padding: 12,
                  transition: 'background-color 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                };

            return (
            <div
              key={flow.id}
              style={rowStyle}
              onMouseEnter={(event) => {
                event.currentTarget.style.backgroundColor = '#f9fafb';
                event.currentTarget.style.borderColor = '#e5e7eb';
                event.currentTarget.style.boxShadow = '0 8px 20px rgba(15, 23, 42, 0.08)';
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.backgroundColor = '#ffffff';
                event.currentTarget.style.borderColor = '#f3f4f6';
                event.currentTarget.style.boxShadow = 'none';
              }}
            >
              {isMobile ? (
                <div style={{ display: 'grid', gap: 10 }}>
                  <div style={{ fontWeight: 700, color: '#111827', fontSize: 16 }}>{flow.name}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'minmax(88px, auto) 1fr', gap: '6px 12px', color: '#4b5563', fontSize: 14 }}>
                    <span style={{ fontWeight: 600, color: '#6b7280' }}>Trigger</span>
                    <span>{flow.trigger_type}</span>
                    <span style={{ fontWeight: 600, color: '#6b7280' }}>Valor</span>
                    <span>{flow.trigger_value || '—'}</span>
                    <span style={{ fontWeight: 600, color: '#6b7280' }}>Status</span>
                    <span>{(flow as FlowItem & { status?: string }).status || '—'}</span>
                  </div>
                </div>
              ) : (
                <>
                  <span style={{ fontWeight: 600, color: '#111827' }}>{flow.name}</span>
                  <span style={{ color: '#6b7280' }}>{flow.trigger_type}</span>
                  <span style={{ color: '#6b7280' }}>{flow.trigger_value || '—'}</span>
                  <span style={{ color: '#6b7280' }}>{(flow as FlowItem & { status?: string }).status || '—'}</span>
                </>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'none', gap: 8, alignItems: 'stretch' }}>
                <button
                  onClick={() => openEdit(flow)}
                  style={{
                    backgroundColor: '#f3f4f6',
                    color: '#374151',
                    border: '1px solid #d1d5db',
                    borderRadius: 8,
                    padding: isMobile ? '12px 14px' : '6px 12px',
                    fontSize: 13,
                    fontWeight: 600,
                    minHeight: isMobile ? 44 : undefined,
                    cursor: 'pointer',
                  }}
                >
                  Editar
                </button>
                <Link
                  href={`/dashboard/flows/${flow.id}/analytics`}
                  style={{
                    backgroundColor: '#f3f4f6',
                    color: '#374151',
                    border: '1px solid #d1d5db',
                    borderRadius: 8,
                    padding: isMobile ? '12px 14px' : '6px 12px',
                    fontSize: 13,
                    fontWeight: 600,
                    minHeight: isMobile ? 44 : undefined,
                    textDecoration: 'none',
                  }}
                >
                  Analytics
                </Link>
                <button
                  onClick={() => onDuplicate(flow.id)}
                  style={{
                    backgroundColor: '#f3f4f6',
                    color: '#374151',
                    border: '1px solid #d1d5db',
                    borderRadius: 8,
                    padding: isMobile ? '12px 14px' : '6px 12px',
                    fontSize: 13,
                    fontWeight: 600,
                    minHeight: isMobile ? 44 : undefined,
                    cursor: 'pointer',
                  }}
                >
                  Duplicar
                </button>
                <button
                  onClick={() => onDelete(flow.id)}
                  style={{
                    backgroundColor: '#fef2f2',
                    color: '#b91c1c',
                    border: '1px solid #fecaca',
                    borderRadius: 8,
                    padding: isMobile ? '12px 14px' : '6px 12px',
                    fontSize: 13,
                    fontWeight: 600,
                    minHeight: isMobile ? 44 : undefined,
                    cursor: 'pointer',
                  }}
                >
                  Deletar
                </button>
                <Link
                  href={`/dashboard/flow-builder?flow_id=${flow.id}`}
                  style={{
                    backgroundColor: '#2563eb',
                    color: '#ffffff',
                    border: '1px solid #1d4ed8',
                    borderRadius: 8,
                    padding: isMobile ? '12px 14px' : '8px 14px',
                    fontSize: 14,
                    fontWeight: 700,
                    minHeight: isMobile ? 44 : undefined,
                    textDecoration: 'none',
                  }}
                >
                  Abrir builder
                </Link>
              </div>
            </div>
          );
          })}
        </div>
      )}

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
