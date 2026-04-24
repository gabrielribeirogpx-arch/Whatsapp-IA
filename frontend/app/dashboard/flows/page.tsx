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

    if (editingFlow) {
      await updateFlow(editingFlow.id, form);
    } else {
      await createFlow(form);
    }

    setIsOpen(false);
    await loadFlows();
  };

  const onDelete = async (flowId: string) => {
    await deleteFlow(flowId);
    await loadFlows();
  };

  const onDuplicate = async (flowId: string) => {
    await duplicateFlow(flowId);
    await loadFlows();
    setToastMessage('Flow duplicado com sucesso');
    setTimeout(() => setToastMessage(null), 3000);
  };

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1>Flows</h1>
        <button onClick={openCreate}>Novo fluxo</button>
      </div>

      {loading ? (
        <p>Carregando...</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th align="left">Nome</th>
              <th align="left">Trigger</th>
              <th align="left">Valor</th>
              <th align="left">Ações</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((flow) => (
              <tr key={flow.id}>
                <td>{flow.name}</td>
                <td>{flow.trigger_type}</td>
                <td>{flow.trigger_value || '-'}</td>
                <td style={{ display: 'flex', gap: 8, padding: '8px 0' }}>
                  <button onClick={() => openEdit(flow)}>Editar</button>
                  <Link href={`/dashboard/flows/${flow.id}/analytics`}>Analytics</Link>
                  <button onClick={() => onDuplicate(flow.id)}>Duplicar</button>
                  <button onClick={() => onDelete(flow.id)}>Deletar</button>
                  <Link href={`/dashboard/flow-builder?flow_id=${flow.id}`}>Abrir builder</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
